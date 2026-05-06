"""Git MCP tools — local git repository operations via CLI."""
import logging
import os
import subprocess
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("harqis-mcp.git")


def _validate_git_arg(arg: str, name: str) -> None:
    """Reject user-supplied git arguments that look like options.

    Without this guard, an attacker-controlled branch / URL / path argument
    can mutate into a git option (CVE-2017-1000117 family). Always pair this
    with a ``--`` separator before positional arguments to subprocess.

    Empty strings and non-strings are also rejected.
    """
    if not isinstance(arg, str) or not arg:
        raise ValueError(f"Git argument {name!r} must be a non-empty string")
    if arg.startswith("-"):
        raise ValueError(
            f"Git argument {name!r}={arg!r} starts with '-' and would be parsed "
            "as an option — refusing for argument-injection safety."
        )


def _run(args: list[str], cwd: Optional[str] = None, timeout: int = 60) -> dict:
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True,
            cwd=cwd or os.getcwd(),
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "timeout", "success": False}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": "git not found", "success": False}


def register_git_tools(mcp: FastMCP):

    @mcp.tool()
    def git_status(path: str = ".") -> dict:
        """Get the working tree status of a git repository.

        Args:
            path: Path to the git repository (default: current directory).
        """
        logger.info("Tool called: git_status path=%s", path)
        result = _run(["status", "--short", "--branch"], cwd=path)
        logger.info("git_status success=%s", result["success"])
        return result

    @mcp.tool()
    def git_log(path: str = ".", max_count: int = 20, oneline: bool = True) -> dict:
        """Show commit history for a repository.

        Args:
            path:      Path to the git repository.
            max_count: Maximum number of commits to show (default: 20).
            oneline:   Use compact one-line format (default: True).
        """
        logger.info("Tool called: git_log path=%s max_count=%d", path, max_count)
        args = ["log", f"--max-count={max_count}"]
        if oneline:
            args.append("--oneline")
        result = _run(args, cwd=path)
        logger.info("git_log success=%s", result["success"])
        return result

    @mcp.tool()
    def git_diff(path: str = ".", staged: bool = False, file_path: Optional[str] = None) -> dict:
        """Show changes in the working tree or staged changes.

        Args:
            path:      Path to the git repository.
            staged:    Show staged (cached) changes instead of unstaged (default: False).
            file_path: Restrict diff to a specific file or directory.
        """
        logger.info("Tool called: git_diff path=%s staged=%s", path, staged)
        args = ["diff"]
        if staged:
            args.append("--cached")
        if file_path:
            args += ["--", file_path]
        result = _run(args, cwd=path)
        logger.info("git_diff success=%s", result["success"])
        return result

    @mcp.tool()
    def git_branch(path: str = ".", all_branches: bool = False) -> dict:
        """List branches in a git repository.

        Args:
            path:         Path to the git repository.
            all_branches: Include remote-tracking branches (default: False).
        """
        logger.info("Tool called: git_branch path=%s all=%s", path, all_branches)
        args = ["branch", "-v"]
        if all_branches:
            args.append("--all")
        result = _run(args, cwd=path)
        logger.info("git_branch success=%s", result["success"])
        return result

    @mcp.tool()
    def git_checkout(branch: str, path: str = ".", create: bool = False) -> dict:
        """Checkout or create a branch in a git repository.

        Args:
            branch: Branch name to checkout or create.
            path:   Path to the git repository.
            create: Create the branch if it does not exist (default: False).
        """
        logger.info("Tool called: git_checkout branch=%s create=%s", branch, create)
        _validate_git_arg(branch, "branch")
        # `--` separates options from positional args so a branch named
        # "--upload-pack=evil" can't be parsed as a git option.
        args = ["checkout"]
        if create:
            args.append("-b")
        args += ["--", branch]
        result = _run(args, cwd=path)
        logger.info("git_checkout success=%s", result["success"])
        return result

    @mcp.tool()
    def git_pull(path: str = ".", remote: str = "origin", branch: Optional[str] = None) -> dict:
        """Pull latest changes from a remote repository.

        Args:
            path:   Path to the git repository.
            remote: Remote name (default: origin).
            branch: Branch to pull (default: current branch).
        """
        logger.info("Tool called: git_pull path=%s remote=%s", path, remote)
        _validate_git_arg(remote, "remote")
        if branch:
            _validate_git_arg(branch, "branch")
        args = ["pull", remote]
        if branch:
            args.append(branch)
        result = _run(args, cwd=path, timeout=120)
        logger.info("git_pull success=%s", result["success"])
        return result

    @mcp.tool()
    def git_commit(
        message: str,
        path: str = ".",
        add_all: bool = False,
        author_name: str = "claude[bot]",
        author_email: str = "claude[bot]@users.noreply.github.com",
    ) -> dict:
        """Stage and commit changes in a git repository.

        Args:
            message:      Commit message.
            path:         Path to the git repository.
            add_all:      Stage all modified/deleted tracked files before committing (default: False).
            author_name:  Git author name (default: claude[bot]).
            author_email: Git author email.
        """
        logger.info("Tool called: git_commit path=%s add_all=%s", path, add_all)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
        if add_all:
            add_result = subprocess.run(
                ["git", "add", "-u"],
                capture_output=True, text=True,
                cwd=path or os.getcwd(), env=env,
            )
            if add_result.returncode != 0:
                return {
                    "returncode": add_result.returncode,
                    "stdout": add_result.stdout.strip(),
                    "stderr": add_result.stderr.strip(),
                    "success": False,
                }
        try:
            result = subprocess.run(
                ["git", "commit", "-m", message],
                capture_output=True, text=True,
                cwd=path or os.getcwd(), env=env, timeout=60,
            )
            out = {
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            out = {"returncode": -1, "stdout": "", "stderr": "timeout", "success": False}
        logger.info("git_commit success=%s", out["success"])
        return out

    @mcp.tool()
    def git_push(
        path: str = ".",
        remote: str = "origin",
        branch: Optional[str] = None,
        set_upstream: bool = False,
    ) -> dict:
        """Push commits to a remote repository.

        Args:
            path:         Path to the git repository.
            remote:       Remote name (default: origin).
            branch:       Branch to push (default: current branch).
            set_upstream: Set the upstream tracking reference (default: False).
        """
        logger.info("Tool called: git_push path=%s remote=%s", path, remote)
        _validate_git_arg(remote, "remote")
        if branch:
            _validate_git_arg(branch, "branch")
        args = ["push", remote]
        if branch:
            args.append(branch)
        if set_upstream:
            args += ["-u", remote, branch or "HEAD"]
        result = _run(args, cwd=path, timeout=120)
        logger.info("git_push success=%s", result["success"])
        return result

    @mcp.tool()
    def git_clone(url: str, destination: Optional[str] = None, depth: Optional[int] = None) -> dict:
        """Clone a git repository.

        Args:
            url:         Repository URL to clone.
            destination: Local path to clone into (default: derived from repo name).
            depth:       Shallow clone depth — number of commits to fetch (default: full clone).
        """
        logger.info("Tool called: git_clone url=%s destination=%s", url, destination)
        _validate_git_arg(url, "url")
        if destination:
            _validate_git_arg(destination, "destination")
        # Build options first, then `--`, then positional args. git accepts
        # the URL after `--`, so this is the safe form even though it differs
        # from the typical "git clone URL DEST" CLI mental model.
        args = ["clone"]
        if depth:
            args += ["--depth", str(depth)]
        args.append("--")
        args.append(url)
        if destination:
            args.append(destination)
        result = _run(args, timeout=300)
        logger.info("git_clone success=%s", result["success"])
        return result

    @mcp.tool()
    def git_show_file(file_path: str, ref: str = "HEAD", repo_path: str = ".") -> dict:
        """Show the content of a file at a specific git ref.

        Args:
            file_path: Path to the file relative to the repository root.
            ref:       Git ref (commit hash, branch, tag). Default: HEAD.
            repo_path: Path to the git repository.
        """
        logger.info("Tool called: git_show_file file=%s ref=%s", file_path, ref)
        result = _run(["show", f"{ref}:{file_path}"], cwd=repo_path)
        logger.info("git_show_file success=%s", result["success"])
        return result
