import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.orgo.config import CONFIG
from apps.orgo.references.web.api.workspaces import ApiServiceOrgoWorkspaces
from apps.orgo.references.web.api.computers import ApiServiceOrgoComputers
from apps.orgo.references.web.api.files import ApiServiceOrgoFiles

logger = logging.getLogger("harqis-mcp.orgo")


def register_orgo_tools(mcp: FastMCP):

    # ── Workspaces ────────────────────────────────────────────────────────

    @mcp.tool()
    def list_orgo_workspaces() -> list[dict]:
        """List all Orgo workspaces in the account.

        Returns:
            List of workspace objects with id, name, created_at, computer_count.
        """
        logger.info("Tool called: list_orgo_workspaces")
        result = ApiServiceOrgoWorkspaces(CONFIG).list_workspaces()
        return result if isinstance(result, list) else []

    @mcp.tool()
    def get_orgo_workspace(workspace_id: str) -> dict:
        """Get details of a specific Orgo workspace.

        Args:
            workspace_id: UUID of the workspace.

        Returns:
            Workspace object with id, name, computer_count, created_at.
        """
        logger.info("Tool called: get_orgo_workspace workspace_id=%s", workspace_id)
        result = ApiServiceOrgoWorkspaces(CONFIG).get_workspace(workspace_id)
        return result if isinstance(result, dict) else {}

    # ── Computers ─────────────────────────────────────────────────────────

    @mcp.tool()
    def get_orgo_computer(computer_id: str) -> dict:
        """Get details and current status of an Orgo cloud computer.

        Args:
            computer_id: Computer ID string.

        Returns:
            Computer object including status: starting|running|stopping|stopped|suspended|error.
        """
        logger.info("Tool called: get_orgo_computer computer_id=%s", computer_id)
        result = ApiServiceOrgoComputers(CONFIG).get_computer(computer_id)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def create_orgo_computer(workspace_id: str, name: str,
                              ram: int = 4, cpu: int = 2,
                              auto_stop_minutes: Optional[int] = None) -> dict:
        """Provision a new Orgo cloud computer (Linux VM).

        Args:
            workspace_id:       UUID of the workspace to create the computer in.
            name:               Unique name for the computer within the workspace.
            ram:                RAM in GB — 4, 8, 16, 32, or 64. Default 4.
            cpu:                CPU cores — 2, 4, 8, or 16. Default 2.
            auto_stop_minutes:  Auto-stop after N minutes idle. None to disable.

        Returns:
            Computer object with id, status, url, and connection details.
        """
        logger.info("Tool called: create_orgo_computer workspace=%s name=%s", workspace_id, name)
        result = ApiServiceOrgoComputers(CONFIG).create_computer(
            workspace_id=workspace_id, name=name, ram=ram, cpu=cpu,
            auto_stop_minutes=auto_stop_minutes
        )
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def start_orgo_computer(computer_id: str) -> dict:
        """Start a stopped Orgo cloud computer.

        Args:
            computer_id: Computer ID to start.
        """
        logger.info("Tool called: start_orgo_computer computer_id=%s", computer_id)
        result = ApiServiceOrgoComputers(CONFIG).start(computer_id)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def stop_orgo_computer(computer_id: str) -> dict:
        """Stop a running Orgo cloud computer.

        Args:
            computer_id: Computer ID to stop.
        """
        logger.info("Tool called: stop_orgo_computer computer_id=%s", computer_id)
        result = ApiServiceOrgoComputers(CONFIG).stop(computer_id)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def orgo_screenshot(computer_id: str) -> dict:
        """Take a screenshot of an Orgo cloud computer's screen.

        Args:
            computer_id: Computer ID to screenshot.

        Returns:
            Dict containing base64-encoded PNG image data.
        """
        logger.info("Tool called: orgo_screenshot computer_id=%s", computer_id)
        result = ApiServiceOrgoComputers(CONFIG).screenshot(computer_id)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def orgo_bash(computer_id: str, command: str) -> dict:
        """Execute a shell command on an Orgo cloud computer.

        Args:
            computer_id: Computer ID to run the command on.
            command:     Shell command string.

        Returns:
            Dict with 'output' (stdout/stderr combined) and 'success' (bool).
        """
        logger.info("Tool called: orgo_bash computer_id=%s command=%s", computer_id, command)
        result = ApiServiceOrgoComputers(CONFIG).bash(computer_id, command)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def orgo_type(computer_id: str, text: str) -> dict:
        """Type text on an Orgo cloud computer.

        Args:
            computer_id: Computer ID.
            text:        Text to type.
        """
        logger.info("Tool called: orgo_type computer_id=%s", computer_id)
        result = ApiServiceOrgoComputers(CONFIG).type_text(computer_id, text)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def orgo_click(computer_id: str, x: int, y: int,
                   button: str = 'left', double: bool = False) -> dict:
        """Click at screen coordinates on an Orgo cloud computer.

        Args:
            computer_id: Computer ID.
            x:           Horizontal pixel position.
            y:           Vertical pixel position.
            button:      'left' or 'right'. Default 'left'.
            double:      True for double-click. Default False.
        """
        logger.info("Tool called: orgo_click computer_id=%s x=%d y=%d", computer_id, x, y)
        result = ApiServiceOrgoComputers(CONFIG).click(computer_id, x, y, button, double)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def orgo_key(computer_id: str, key: str) -> dict:
        """Send a key press or combination to an Orgo cloud computer.

        Args:
            computer_id: Computer ID.
            key:         Key name or combo — e.g. 'Enter', 'Escape', 'ctrl+c', 'alt+Tab', 'F5'.
        """
        logger.info("Tool called: orgo_key computer_id=%s key=%s", computer_id, key)
        result = ApiServiceOrgoComputers(CONFIG).key(computer_id, key)
        return result if isinstance(result, dict) else {}

    # ── Files ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def list_orgo_files(workspace_id: str, computer_id: Optional[str] = None) -> list[dict]:
        """List files in an Orgo workspace, optionally filtered by computer.

        Args:
            workspace_id: UUID of the workspace.
            computer_id:  Optional computer ID to filter results.

        Returns:
            List of file objects with id, filename, size_bytes, content_type, created_at.
        """
        logger.info("Tool called: list_orgo_files workspace_id=%s", workspace_id)
        result = ApiServiceOrgoFiles(CONFIG).list_files(workspace_id, computer_id)
        return result if isinstance(result, list) else []

    @mcp.tool()
    def download_orgo_file(file_id: str) -> dict:
        """Get a temporary download URL for an Orgo file (expires in 1 hour).

        Args:
            file_id: File ID from list_orgo_files.

        Returns:
            Dict with download URL.
        """
        logger.info("Tool called: download_orgo_file file_id=%s", file_id)
        result = ApiServiceOrgoFiles(CONFIG).download_file(file_id)
        return result if isinstance(result, dict) else {}
