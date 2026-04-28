"""Filesystem MCP tools — local file and directory operations."""
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("harqis-mcp.filesystem")

_MAX_READ_BYTES = 1_000_000  # 1 MB


def register_filesystem_tools(mcp: FastMCP):

    @mcp.tool()
    def fs_read_file(file_path: str, encoding: str = "utf-8") -> dict:
        """Read the contents of a local file.

        Args:
            file_path: Absolute or relative path to the file.
            encoding:  Text encoding (default: utf-8). Use 'binary' to get base64.
        """
        logger.info("Tool called: fs_read_file path=%s", file_path)
        p = Path(file_path).expanduser().resolve()
        if not p.exists():
            return {"success": False, "error": f"File not found: {p}", "content": None}
        if not p.is_file():
            return {"success": False, "error": f"Not a file: {p}", "content": None}
        size = p.stat().st_size
        if size > _MAX_READ_BYTES:
            return {"success": False, "error": f"File too large ({size} bytes)", "content": None}
        if encoding == "binary":
            import base64
            content = base64.b64encode(p.read_bytes()).decode()
        else:
            content = p.read_text(encoding=encoding, errors="replace")
        logger.info("fs_read_file size=%d", size)
        return {"success": True, "path": str(p), "size": size, "content": content}

    @mcp.tool()
    def fs_write_file(file_path: str, content: str, encoding: str = "utf-8", overwrite: bool = True) -> dict:
        """Write text content to a local file.

        Args:
            file_path: Absolute or relative path to write to.
            content:   Text content to write.
            encoding:  Text encoding (default: utf-8).
            overwrite: Overwrite the file if it already exists (default: True).
        """
        logger.info("Tool called: fs_write_file path=%s overwrite=%s", file_path, overwrite)
        p = Path(file_path).expanduser().resolve()
        if p.exists() and not overwrite:
            return {"success": False, "error": f"File already exists: {p}"}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        logger.info("fs_write_file written %d bytes", len(content))
        return {"success": True, "path": str(p), "bytes_written": len(content.encode(encoding))}

    @mcp.tool()
    def fs_list_directory(dir_path: str, show_hidden: bool = False, recursive: bool = False) -> dict:
        """List the contents of a directory.

        Args:
            dir_path:    Absolute or relative path to the directory.
            show_hidden: Include hidden files/directories (default: False).
            recursive:   List contents recursively (default: False).
        """
        logger.info("Tool called: fs_list_directory path=%s recursive=%s", dir_path, recursive)
        p = Path(dir_path).expanduser().resolve()
        if not p.exists():
            return {"success": False, "error": f"Directory not found: {p}", "entries": []}
        if not p.is_dir():
            return {"success": False, "error": f"Not a directory: {p}", "entries": []}
        entries = []
        iterator = p.rglob("*") if recursive else p.iterdir()
        for item in sorted(iterator):
            if not show_hidden and item.name.startswith("."):
                continue
            stat = item.stat()
            entries.append({
                "name": item.name,
                "path": str(item),
                "type": "dir" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else None,
            })
        logger.info("fs_list_directory returned %d entries", len(entries))
        return {"success": True, "path": str(p), "entries": entries, "count": len(entries)}

    @mcp.tool()
    def fs_create_directory(dir_path: str, exist_ok: bool = True) -> dict:
        """Create a directory (and any necessary parent directories).

        Args:
            dir_path: Absolute or relative path to create.
            exist_ok: Don't error if the directory already exists (default: True).
        """
        logger.info("Tool called: fs_create_directory path=%s", dir_path)
        p = Path(dir_path).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=exist_ok)
        logger.info("fs_create_directory created %s", p)
        return {"success": True, "path": str(p)}

    @mcp.tool()
    def fs_delete(path: str, recursive: bool = False) -> dict:
        """Delete a file or directory.

        Args:
            path:      Absolute or relative path to delete.
            recursive: Delete directories and their contents recursively (default: False).
        """
        logger.info("Tool called: fs_delete path=%s recursive=%s", path, recursive)
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"success": False, "error": f"Path not found: {p}"}
        if p.is_dir():
            if not recursive:
                return {"success": False, "error": f"Use recursive=True to delete directories"}
            shutil.rmtree(p)
        else:
            p.unlink()
        logger.info("fs_delete deleted %s", p)
        return {"success": True, "path": str(p)}

    @mcp.tool()
    def fs_copy(src: str, dst: str, overwrite: bool = False) -> dict:
        """Copy a file or directory to a new location.

        Args:
            src:       Source path.
            dst:       Destination path.
            overwrite: Overwrite destination if it exists (default: False).
        """
        logger.info("Tool called: fs_copy src=%s dst=%s", src, dst)
        s = Path(src).expanduser().resolve()
        d = Path(dst).expanduser().resolve()
        if not s.exists():
            return {"success": False, "error": f"Source not found: {s}"}
        if d.exists() and not overwrite:
            return {"success": False, "error": f"Destination already exists: {d}"}
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(str(s), str(d), dirs_exist_ok=overwrite)
        else:
            shutil.copy2(str(s), str(d))
        logger.info("fs_copy done src=%s dst=%s", s, d)
        return {"success": True, "src": str(s), "dst": str(d)}

    @mcp.tool()
    def fs_move(src: str, dst: str) -> dict:
        """Move or rename a file or directory.

        Args:
            src: Source path.
            dst: Destination path.
        """
        logger.info("Tool called: fs_move src=%s dst=%s", src, dst)
        s = Path(src).expanduser().resolve()
        d = Path(dst).expanduser().resolve()
        if not s.exists():
            return {"success": False, "error": f"Source not found: {s}"}
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        logger.info("fs_move done src=%s dst=%s", s, d)
        return {"success": True, "src": str(s), "dst": str(d)}

    @mcp.tool()
    def fs_file_info(path: str) -> dict:
        """Get metadata about a file or directory.

        Args:
            path: Absolute or relative path.
        """
        logger.info("Tool called: fs_file_info path=%s", path)
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"success": False, "error": f"Path not found: {p}", "info": None}
        import datetime
        stat = p.stat()
        info = {
            "path": str(p),
            "name": p.name,
            "type": "dir" if p.is_dir() else "file",
            "size": stat.st_size,
            "extension": p.suffix,
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
        }
        logger.info("fs_file_info size=%d", stat.st_size)
        return {"success": True, "info": info}

    @mcp.tool()
    def fs_search_files(
        root: str,
        pattern: str,
        max_results: int = 100,
        search_content: Optional[str] = None,
    ) -> dict:
        """Search for files matching a glob pattern, optionally filtering by content.

        Args:
            root:           Directory to search in.
            pattern:        Glob pattern, e.g. '**/*.py', '*.json'.
            max_results:    Maximum number of results to return (default: 100).
            search_content: Optional string to search for within matching files.
        """
        logger.info("Tool called: fs_search_files root=%s pattern=%s", root, pattern)
        r = Path(root).expanduser().resolve()
        if not r.is_dir():
            return {"success": False, "error": f"Not a directory: {r}", "files": []}
        matches = []
        for p in sorted(r.glob(pattern)):
            if len(matches) >= max_results:
                break
            if p.is_file():
                entry = {"path": str(p), "name": p.name, "size": p.stat().st_size}
                if search_content:
                    try:
                        text = p.read_text(errors="ignore")
                        if search_content not in text:
                            continue
                        entry["match"] = True
                    except Exception:
                        continue
                matches.append(entry)
        logger.info("fs_search_files found %d file(s)", len(matches))
        return {"success": True, "root": str(r), "pattern": pattern, "files": matches, "count": len(matches)}
