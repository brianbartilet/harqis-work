# apps/google_apps/references/web/api/sheets_service.py

from __future__ import annotations

from typing import List, Sequence, Any, Optional
from enum import Enum

from apps.google_apps.references.web.discovery import BaseGoogleDiscoveryService


class SheetInputOption(str, Enum):
    RAW = "RAW"
    USER_ENTERED = "USER_ENTERED"


class ApiServiceGoogleSheets(BaseGoogleDiscoveryService):
    """
    Google Sheets API service wrapped around the discovery client.

    Usage pattern:
        sheets = ApiServiceGoogleSheets(CONFIG, scopes_list=[...])
        values = sheets.get_values("Sheet1!A1:C10")
    """

    SERVICE_NAME = "sheets"
    SERVICE_VERSION = "v4"

    def __init__(self, config, scopes_list: Sequence[str], **kwargs) -> None:
        super().__init__(config, scopes_list=scopes_list, **kwargs)

        # Convenience references
        self.spreadsheets = self.service.spreadsheets()

        # Use the local config param directly — self.config/_config is not set
        # in this init path (BaseApiServiceGoogle skips super().__init__ when use_gclient=True)
        self.sheet_id: str = config.app_data["sheet_id"]

        # Optional in-memory buffer helpers
        self.row_data: List[List[Any]] = []
        self.data = {"values": self.row_data}

    # ─────────────────────────────────────────────────────────────
    # Simple value helpers
    # ─────────────────────────────────────────────────────────────

    def get_values(self, range_expression: str) -> List[List[Any]]:
        """
        Read values from a sheet range.

        Args:
            range_expression: e.g. "Sheet1!A1:C10"

        Returns:
            List of rows; each row is a list of cell values.
        """
        result = (
            self.spreadsheets.values()
            .get(spreadsheetId=self.sheet_id, range=range_expression)
            .execute()
        )
        return result.get("values", [])

    def clear_values(self, range_expression: str) -> dict:
        """
        Clear values in the given range.

        Args:
            range_expression: e.g. "Sheet1!A1:Z999"

        Returns:
            API response dict.
        """
        body = {}
        return (
            self.spreadsheets.values()
            .clear(
                spreadsheetId=self.sheet_id,
                range=range_expression,
                body=body,
            )
            .execute()
        )

    def update_values(
        self,
        range_expression: str,
        values: Sequence[Sequence[Any]],
        input_option: SheetInputOption = SheetInputOption.RAW,
    ) -> dict:
        """
        Write/update values in a given range.

        Args:
            range_expression: e.g. "Sheet1!A1"
            values: 2D list of values [[...], [...], ...]
            input_option: RAW or USER_ENTERED (see SheetInputOption)

        Returns:
            API response dict.
        """
        body = {"values": values}
        return (
            self.spreadsheets.values()
            .update(
                spreadsheetId=self.sheet_id,
                range=range_expression,
                valueInputOption=input_option.value,
                body=body,
            )
            .execute()
        )

    def append_values(
        self,
        range_expression: str,
        values: Sequence[Sequence[Any]],
        input_option: SheetInputOption = SheetInputOption.RAW,
        insert_rows: bool = True,
    ) -> dict:
        """
        Append rows after the last row of data in a range (never overwrites data).

        Args:
            range_expression: table to append to, e.g. "Trades!A:M"
            values: 2D list of values [[...], [...], ...]
            input_option: RAW or USER_ENTERED (see SheetInputOption)
            insert_rows: True inserts new sheet rows (shifting everything below, in
                every column); False writes into the empty rows under the table, which
                keeps side-by-side blocks on the same tab in place.

        Returns:
            API response dict.
        """
        body = {"values": values}
        return (
            self.spreadsheets.values()
            .append(
                spreadsheetId=self.sheet_id,
                range=range_expression,
                valueInputOption=input_option.value,
                insertDataOption="INSERT_ROWS" if insert_rows else "OVERWRITE",
                body=body,
            )
            .execute()
        )

    def get_tab_id(self, title: str) -> int:
        """Numeric sheetId (gid) of a tab, looked up by its title."""
        meta = self.spreadsheets.get(spreadsheetId=self.sheet_id, fields="sheets.properties(sheetId,title)").execute()
        for sheet in meta.get("sheets", []):
            if sheet["properties"]["title"] == title:
                return sheet["properties"]["sheetId"]
        raise KeyError(f"Tab '{title}' not found")

    def add_tab(self, title: str, frozen_rows: int = 1) -> int:
        """Create a new tab (optionally with frozen header rows); returns its sheetId."""
        body = {"requests": [{"addSheet": {"properties": {
            "title": title, "gridProperties": {"frozenRowCount": frozen_rows},
        }}}]}
        reply = self.spreadsheets.batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()
        return reply["replies"][0]["addSheet"]["properties"]["sheetId"]

    def tab_titles(self) -> List[str]:
        """Titles of all tabs, in order."""
        meta = self.spreadsheets.get(spreadsheetId=self.sheet_id, fields="sheets.properties.title").execute()
        return [sheet["properties"]["title"] for sheet in meta.get("sheets", [])]

    def insert_rows(self, title: str, start_index: int, count: int) -> dict:
        """
        Insert empty rows into a tab, shifting rows below down.

        Formulas whose ranges span the insertion point expand automatically, and the
        new rows inherit formatting from the row above.

        Args:
            title: tab name
            start_index: 0-based row index to insert at (row 26 in the UI is index 25)
            count: number of rows

        Returns:
            API response dict.
        """
        body = {"requests": [{"insertDimension": {
            "range": {"sheetId": self.get_tab_id(title), "dimension": "ROWS",
                      "startIndex": start_index, "endIndex": start_index + count},
            "inheritFromBefore": start_index > 0,
        }}]}
        return self.spreadsheets.batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()

    # ─────────────────────────────────────────────────────────────
    # Optional buffered helpers (similar to your existing pattern)
    # ─────────────────────────────────────────────────────────────

    def reset_buffer(self) -> None:
        """Clear the in-memory row buffer."""
        self.row_data.clear()

    def set_headers(self, headers: Sequence[Any]) -> None:
        """Set header row into the buffer (first row)."""
        self.reset_buffer()
        self.row_data.append(list(headers))

    def add_row(self, row: Sequence[Any]) -> None:
        """Append a single row to the buffer."""
        self.row_data.append(list(row))

    def set_rows(self, rows: Sequence[Sequence[Any]]) -> None:
        """Replace buffer rows (excluding headers, if you want headers separate)."""
        self.reset_buffer()
        for r in rows:
            self.row_data.append(list(r))

    def flush_buffer(
        self,
        range_expression: str,
        input_option: SheetInputOption = SheetInputOption.USER_ENTERED,
    ) -> dict:
        """
        Push the current buffer `self.row_data` to the sheet.

        Args:
            range_expression: top-left cell to start writing, e.g. "Sheet1!A1"
            input_option: RAW or USER_ENTERED

        Returns:
            API response dict.
        """
        return self.update_values(range_expression, self.row_data, input_option)
