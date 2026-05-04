"""AppSheet Tables service — Find/Add/Edit/Delete rows in a table.

Every method maps to a single POST against:
    /apps/{appId}/tables/{tableName}/Action

The Action verb is one of `Find`, `Add`, `Edit`, `Delete`. The response is
typically a list of row dicts (Add/Edit/Find return the affected rows;
Delete usually returns an empty body).

Selector expressions follow AppSheet expression syntax, e.g.:
    Filter("Tasks", [Status] = "Open")
    Filter("Inventory", AND([Qty] > 0, [Active] = TRUE))

Docs: https://support.google.com/appsheet/answer/10105768
"""
from typing import Any, Optional

from apps.appsheet.references.dto.tables import (
    DtoAppSheetActionResult,
    DtoAppSheetRow,
)
from apps.appsheet.references.web.base_api_service import BaseApiServiceAppSheet


def _wrap(action: str, table: str, payload: Any) -> DtoAppSheetActionResult:
    if isinstance(payload, list):
        rows = [DtoAppSheetRow.from_api(r) for r in payload]
    elif isinstance(payload, dict):
        rows = [DtoAppSheetRow.from_api(payload)]
    else:
        rows = []
    return DtoAppSheetActionResult(action=action, table=table, rows=rows, raw=payload)


class ApiServiceAppSheetTables(BaseApiServiceAppSheet):
    """Read/write rows in an AppSheet table."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def find_rows(
        self,
        table: str,
        selector: Optional[str] = None,
        app_id: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> DtoAppSheetActionResult:
        """Read rows from a table.

        Args:
            table:      Table name as defined in the AppSheet app.
            selector:   Optional AppSheet expression that filters/orders the
                        rows server-side, e.g. `Filter("Tasks", [Status]="Open")`.
                        When omitted, AppSheet returns every row.
            app_id:     AppSheet app id. Defaults to `default_app_id` in config.
            properties: Extra Properties to merge into the request body
                        (Locale is set automatically).
        """
        props = dict(properties or {})
        if selector:
            props["Selector"] = selector
        payload = self._action(
            table_name=table,
            action="Find",
            properties=props,
            app_id=app_id,
        )
        return _wrap("Find", table, payload)

    def add_rows(
        self,
        table: str,
        rows: list[dict[str, Any]],
        app_id: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> DtoAppSheetActionResult:
        """Insert one or more rows.

        Args:
            table: Table name.
            rows:  List of column-name → value dicts. AppSheet auto-fills
                   any column with an Initial Value formula left out here.
            app_id: AppSheet app id (falls back to default_app_id).
            properties: Extra Properties to merge.
        """
        payload = self._action(
            table_name=table,
            action="Add",
            rows=rows,
            properties=properties,
            app_id=app_id,
        )
        return _wrap("Add", table, payload)

    def get_headers(
        self,
        table: str,
        app_id: Optional[str] = None,
        include_system: bool = False,
    ) -> list[str]:
        """Discover column names by sampling rows from the table.

        AppSheet exposes no schema endpoint, so columns are inferred from
        the keys of the returned rows. System columns (any key starting
        with `_`, e.g. `_RowNumber`, `_ComputedKey`) are excluded unless
        `include_system=True`.
        """
        payload = self._action(table_name=table, action="Find", app_id=app_id)
        if not isinstance(payload, list):
            return []
        keys: list[str] = []
        seen: set[str] = set()
        for row in payload:
            if not isinstance(row, dict):
                continue
            for k in row.keys():
                if k in seen:
                    continue
                if not include_system and k.startswith("_"):
                    continue
                seen.add(k)
                keys.append(k)
        return keys

    def add_row(
        self,
        table: str,
        data: dict[str, Any],
        app_id: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> DtoAppSheetActionResult:
        """Add a single row, dropping any key not present in the table's headers.

        Looks up the table's columns via `get_headers`, keeps only the
        intersection with `data`, then forwards to `add_rows`. Use
        `add_rows` directly to bypass the filter.
        """
        header_set = set(self.get_headers(table, app_id=app_id))
        filtered = {k: v for k, v in data.items() if k in header_set}
        return self.add_rows(
            table=table,
            rows=[filtered],
            app_id=app_id,
            properties=properties,
        )

    def edit_rows(
        self,
        table: str,
        rows: list[dict[str, Any]],
        app_id: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> DtoAppSheetActionResult:
        """Update existing rows.

        Each item in `rows` MUST include the table's key column(s) so
        AppSheet can find the row to update; other columns are overwritten
        with the new values.
        """
        payload = self._action(
            table_name=table,
            action="Edit",
            rows=rows,
            properties=properties,
            app_id=app_id,
        )
        return _wrap("Edit", table, payload)

    def delete_rows(
        self,
        table: str,
        rows: list[dict[str, Any]],
        app_id: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> DtoAppSheetActionResult:
        """Delete rows. Each item must include the key column value."""
        payload = self._action(
            table_name=table,
            action="Delete",
            rows=rows,
            properties=properties,
            app_id=app_id,
        )
        return _wrap("Delete", table, payload)
