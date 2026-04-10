"""
Filesystem and shell tools for agents.

Cross-platform: uses pathlib.Path everywhere; bash/shell is invoked via
subprocess with shell=True which works on both Windows and Linux.
"""

from __future__ import annotations

import fnmatch
import logging
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

from agents.kanban.permissions.enforcer import PermissionEnforcer

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


class _BaseTool:
    name: str
    description: str
    input_schema: dict

    def run(self, **kwargs): ...


class ReadFileTool(_BaseTool):
    name = "read_file"
    description = (
        "Read the text contents of a file. "
        "Returns the file content as a string."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative file path to read.",
            },
            "start_line": {
                "type": "integer",
                "description": "Optional 1-based line to start from (inclusive).",
            },
            "end_line": {
                "type": "integer",
                "description": "Optional 1-based line to stop at (inclusive).",
            },
        },
        "required": ["path"],
    }

    def __init__(self, enforcer: PermissionEnforcer):
        self._enforcer = enforcer

    def run(self, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        self._enforcer.check_filesystem(path)
        p = Path(path)
        if not p.exists():
            return f"ERROR: File not found: {path}"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        if start_line or end_line:
            lo = (start_line or 1) - 1
            hi = end_line or len(lines)
            lines = lines[lo:hi]
        return "".join(lines)


class WriteFileTool(_BaseTool):
    name = "write_file"
    description = (
        "Write text content to a file, creating parent directories as needed. "
        "Overwrites existing content."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative file path to write.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write.",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, enforcer: PermissionEnforcer):
        self._enforcer = enforcer

    def run(self, path: str, content: str) -> str:
        self._enforcer.check_filesystem(path)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} characters to {path}"


class GlobTool(_BaseTool):
    name = "glob"
    description = (
        "Find files matching a glob pattern. "
        "Returns a newline-separated list of matching paths."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '**/*.py' or 'src/**/*.ts'.",
            },
            "base_dir": {
                "type": "string",
                "description": "Directory to search from. Defaults to current directory.",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, enforcer: PermissionEnforcer):
        self._enforcer = enforcer

    def run(self, pattern: str, base_dir: str = ".") -> str:
        base = Path(base_dir)
        matches = sorted(str(p) for p in base.glob(pattern))
        if not matches:
            return f"No files matched: {pattern}"
        # Filter to allowed paths
        allowed = []
        for m in matches:
            try:
                self._enforcer.check_filesystem(m)
                allowed.append(m)
            except Exception:
                pass
        return "\n".join(allowed) if allowed else "No accessible files matched."


class GrepTool(_BaseTool):
    name = "grep"
    description = (
        "Search for a regex pattern in files. "
        "Returns matching lines with file path and line number."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search. Defaults to '.'.",
            },
            "glob": {
                "type": "string",
                "description": "File glob filter, e.g. '*.py'. Only used when path is a directory.",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive search. Default false.",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, enforcer: PermissionEnforcer):
        self._enforcer = enforcer

    def run(
        self,
        pattern: str,
        path: str = ".",
        glob: str = "*",
        case_insensitive: bool = False,
    ) -> str:
        import re

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Invalid regex: {e}"

        p = Path(path)
        files = [p] if p.is_file() else list(p.rglob(glob))
        results: list[str] = []

        for f in files:
            if not f.is_file():
                continue
            try:
                self._enforcer.check_filesystem(str(f))
            except Exception:
                continue
            try:
                for i, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if regex.search(line):
                        results.append(f"{f}:{i}: {line.rstrip()}")
            except OSError:
                pass

        if not results:
            return f"No matches for '{pattern}'"
        return "\n".join(results[:500])  # cap output


class BashTool(_BaseTool):
    name = "bash"
    description = (
        "Execute a shell command and return stdout + stderr. "
        "On Windows this runs via cmd.exe; on Linux/macOS via /bin/bash. "
        "Working directory is the agent's configured working_directory."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default 60.",
            },
        },
        "required": ["command"],
    }

    def __init__(self, enforcer: PermissionEnforcer, cwd: Optional[str] = None):
        self._enforcer = enforcer
        self._cwd = cwd

    def run(self, command: str, timeout: int = 60) -> str:
        self._enforcer.check_tool("bash")
        logger.debug("bash: %s", command)
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._cwd or None,
                # On Windows, use cmd.exe; on POSIX use /bin/bash
                executable=None if _IS_WINDOWS else "/bin/bash",
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"ERROR: Command timed out after {timeout}s"
        except Exception as e:
            return f"ERROR: {e}"
