"""AppSheet MCP tools — query and mutate rows in AppSheet tables."""
import logging
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from apps.appsheet.config import CONFIG
from apps.appsheet.references.web.api.tables import ApiServiceAppSheetTables

logger = logging.getLogger("harqis-mcp.appsheet")


def register_appsheet_tools(mcp: FastMCP):

    @mcp.tool()
    def appsheet_find_rows(
        table: str,
        selector: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> list[dict]:
        """Read rows from an AppSheet table — returns row dicts.

        Args:
            table:    Name of the table as defined inside the AppSheet app.
            selector: Optional AppSheet expression to filter/sort server-side,
                      e.g. `Filter("Tasks", [Status] = "Open")`. Omit to fetch
                      every row.
            app_id:   AppSheet app id. Defaults to APPSHEET.default_app_id.
        """
        logger.info("Tool called: appsheet_find_rows table=%s app_id=%s", table, app_id)
        svc = ApiServiceAppSheetTables(CONFIG)
        result = svc.find_rows(table=table, selector=selector, app_id=app_id)
        rows = [r.fields for r in (result.rows or [])]
        logger.info("appsheet_find_rows returned %d row(s)", len(rows))
        return rows

    @mcp.tool()
    def appsheet_add_rows(
        table: str,
        rows: list[dict[str, Any]],
        app_id: Optional[str] = None,
    ) -> list[dict]:
        """Insert one or more rows into an AppSheet table.

        Args:
            table:  Table name.
            rows:   List of column-value dicts, e.g. `[{"Name": "Acme", "Status": "New"}]`.
            app_id: AppSheet app id. Defaults to APPSHEET.default_app_id.
        """
        logger.info("Tool called: appsheet_add_rows table=%s count=%d", table, len(rows))
        svc = ApiServiceAppSheetTables(CONFIG)
        result = svc.add_rows(table=table, rows=rows, app_id=app_id)
        out = [r.fields for r in (result.rows or [])]
        logger.info("appsheet_add_rows inserted %d row(s)", len(out))
        return out

    @mcp.tool()
    def appsheet_edit_rows(
        table: str,
        rows: list[dict[str, Any]],
        app_id: Optional[str] = None,
    ) -> list[dict]:
        """Update existing rows. Each row must include the table's key column.

        Args:
            table:  Table name.
            rows:   List of column-value dicts including the key column(s)
                    so AppSheet can find the target row.
            app_id: AppSheet app id. Defaults to APPSHEET.default_app_id.
        """
        logger.info("Tool called: appsheet_edit_rows table=%s count=%d", table, len(rows))
        svc = ApiServiceAppSheetTables(CONFIG)
        result = svc.edit_rows(table=table, rows=rows, app_id=app_id)
        out = [r.fields for r in (result.rows or [])]
        logger.info("appsheet_edit_rows updated %d row(s)", len(out))
        return out

    @mcp.tool()
    def appsheet_delete_rows(
        table: str,
        rows: list[dict[str, Any]],
        app_id: Optional[str] = None,
    ) -> dict:
        """Delete rows. Each row must include the key column value.

        Args:
            table:  Table name.
            rows:   List of dicts containing the key column(s) of rows to delete.
            app_id: AppSheet app id. Defaults to APPSHEET.default_app_id.
        """
        logger.info("Tool called: appsheet_delete_rows table=%s count=%d", table, len(rows))
        svc = ApiServiceAppSheetTables(CONFIG)
        result = svc.delete_rows(table=table, rows=rows, app_id=app_id)
        logger.info("appsheet_delete_rows done")
        return {"deleted": len(rows), "raw": result.raw if isinstance(result.raw, (dict, list, str)) else None}
