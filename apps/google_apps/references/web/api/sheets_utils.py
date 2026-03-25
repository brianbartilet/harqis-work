"""
Spreadsheet utility layer for Google Sheets.

Provides SpreadsheetUtils, a high-level query interface on top of
ApiServiceGoogleSheets. Data is fetched once and cached in memory;
all query methods operate on the local cache without additional API
calls unless load() is called again.

Typical workflow
----------------
    from apps.google_apps.references.web.api.sheets import ApiServiceGoogleSheets
    from apps.google_apps.references.web.api.sheets_utils import SpreadsheetUtils

    service = ApiServiceGoogleSheets(config, scopes_list=[...])
    utils = SpreadsheetUtils(service, data_range="A:F").load()

    today_total   = utils.sum_column_today("Amount", "Date")
    week_rows     = utils.get_rows_this_week("Date")
    by_category   = utils.group_sum_by_column("Amount", "Category")
    record        = utils.get_row_by_id("ID", "uuid-001")

Date parsing
------------
Cell dates are auto-detected from common text formats (ISO, US, EU,
long-form) and from Google Sheets serial numbers (integer days since
1899-12-30).  Rows with unparseable or missing dates are silently
excluded from date-filtered queries.

Amount parsing
--------------
Currency symbols ($, ₱, €, £, ¥) and thousand-separators are stripped
before conversion.  Non-numeric cells are silently excluded from sums
and averages.

Column resolution
-----------------
All col/date_col/amount_col arguments accept the **header name** as it
appears in the sheet (case-insensitive, leading/trailing whitespace
ignored).  A KeyError is raised immediately if the header cannot be
found, listing the available headers.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from apps.google_apps.references.web.api.sheets import ApiServiceGoogleSheets

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

# Date formats tried in order when parsing cell values.
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y/%m/%d",
]

# Google Sheets serial date epoch (Dec 30 1899).
_SHEETS_EPOCH = date(1899, 12, 30)


def _parse_date(value: Any) -> Optional[date]:
    """
    Convert a raw cell value to a Python ``date``.

    Handles:

    * Google Sheets **serial numbers** — integers (or integer-valued
      floats/strings) in the plausible range 1 000 – 200 000, interpreted
      as days since the Sheets epoch (1899-12-30).
    * **Text dates** — tried against every pattern in ``_DATE_FORMATS``
      in order until one succeeds.

    Returns ``None`` for empty, ``None``, or unparseable values.

    Args:
        value: Raw cell contents from the Sheets API.

    Returns:
        Parsed ``date``, or ``None`` if the value cannot be interpreted.
    """
    if value is None or value == "":
        return None
    # Serial number (int or float stored as string)
    try:
        serial = int(float(str(value)))
        if 1000 < serial < 200000:   # plausible Sheets serial range
            return _SHEETS_EPOCH + timedelta(days=serial)
    except (ValueError, OverflowError):
        pass
    # Text date
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: Any) -> Optional[Decimal]:
    """
    Convert a raw cell value to a ``Decimal`` amount.

    Strips common currency symbols (``$``, ``₱``, ``€``, ``£``, ``¥``)
    and their ISO codes (``USD``, ``PHP``, ``EUR``), as well as thousand
    separators (commas) and surrounding whitespace, before attempting
    conversion.

    Returns ``None`` for empty, ``None``, or non-numeric values so callers
    can safely skip unparseable cells rather than raising.

    Args:
        value: Raw cell contents from the Sheets API.

    Returns:
        ``Decimal`` amount, or ``None`` if the value is not numeric.
    """
    if value is None or value == "":
        return None
    cleaned = str(value).strip().replace(",", "").replace(" ", "")
    for ch in ("$", "₱", "€", "£", "¥", "USD", "PHP", "EUR"):
        cleaned = cleaned.replace(ch, "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# Main utility class
# ---------------------------------------------------------------------------

class SpreadsheetUtils:
    """
    High-level query interface on top of :class:`ApiServiceGoogleSheets`.

    The sheet is fetched **once** via :meth:`load` and cached as a list of
    dicts keyed by header name.  All subsequent queries run against the
    in-memory cache — no additional API calls are made unless :meth:`load`
    is called again.

    Column names are resolved **case-insensitively** against the header row
    so callers never need to worry about exact casing or leading/trailing
    spaces.

    Parameters
    ----------
    service:
        An initialised :class:`ApiServiceGoogleSheets` instance.
    data_range:
        A1-notation range to fetch, e.g. ``"A:F"`` or ``"Sheet1!A1:G500"``.
        Defaults to ``"A:Z"`` (entire sheet).
    header_row_index:
        Zero-based index of the row within *data_range* that contains the
        column headers.  Defaults to ``0`` (first row).
    reference_date:
        Override for ``date.today()`` used by convenience methods such as
        :meth:`sum_column_today` and :meth:`get_rows_this_week`.  Primarily
        useful in tests where a fixed, predictable date is required.

    Examples
    --------
    Basic usage::

        service = ApiServiceGoogleSheets(config, scopes_list=[...])
        utils   = SpreadsheetUtils(service, data_range="A:F").load()

        # Total spend today
        print(utils.sum_column_today("Amount", "Date"))

        # All rows this week as JSON-ready dicts
        rows = utils.get_rows_this_week("Date")

        # Spend by category for the current week
        breakdown = utils.group_sum_by_column(
            "Amount", "Category",
            date_col="Date",
            start=monday, end=sunday,
        )
    """

    def __init__(
        self,
        service: ApiServiceGoogleSheets,
        data_range: str = "A:Z",
        header_row_index: int = 0,
        reference_date: Optional[date] = None,
    ) -> None:
        self._service = service
        self._data_range = data_range
        self._header_row_index = header_row_index
        self._reference_date = reference_date
        self._headers: List[str] = []
        self._rows: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Load / refresh
    # ------------------------------------------------------------------

    def load(self) -> "SpreadsheetUtils":
        """
        Fetch all data from the sheet and cache it locally.

        Reads ``data_range`` via the Sheets API, extracts headers from
        ``header_row_index``, and converts every subsequent row into a
        ``dict`` keyed by header name.  Short rows are right-padded with
        empty strings so every dict has an entry for every header.

        Returns:
            ``self`` — allows chaining: ``utils = SpreadsheetUtils(...).load()``
        """
        raw = self._service.get_values(self._data_range)
        if not raw:
            self._headers = []
            self._rows = []
            return self

        self._headers = [str(h).strip() for h in raw[self._header_row_index]]
        self._rows = []
        for raw_row in raw[self._header_row_index + 1:]:
            padded = list(raw_row) + [""] * (len(self._headers) - len(raw_row))
            self._rows.append(dict(zip(self._headers, padded)))
        return self

    @property
    def headers(self) -> List[str]:
        """Ordered list of column header names as read from the sheet."""
        return list(self._headers)

    @property
    def records(self) -> List[Dict[str, Any]]:
        """
        All data rows as a list of dicts keyed by header name.

        Does not include the header row itself.  Each dict has one key per
        header; missing trailing cells are represented as empty strings.
        """
        return list(self._rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today(self) -> date:
        """
        Return the reference date for "today".

        Uses ``reference_date`` if one was supplied at construction time
        (useful in tests), otherwise falls back to ``date.today()``.
        """
        return self._reference_date or date.today()

    def _col(self, name: str) -> str:
        """
        Resolve a user-supplied column name to the exact header string.

        Comparison is case-insensitive and strips leading/trailing whitespace
        from both sides.

        Args:
            name: Column name as supplied by the caller.

        Returns:
            The matching header string exactly as it appears in the sheet.

        Raises:
            KeyError: If no header matches ``name``, including the list of
                available headers in the error message.
        """
        for h in self._headers:
            if h.strip().lower() == name.strip().lower():
                return h
        raise KeyError(f"Column '{name}' not found. Available headers: {self._headers}")

    def _filter_by_date(
        self,
        rows: List[Dict],
        date_col: str,
        start: date,
        end: date,
    ) -> List[Dict]:
        """
        Return rows whose parsed date falls within ``[start, end]`` inclusive.

        Rows with a missing or unparseable date value are silently excluded.

        Args:
            rows:     Source row list to filter.
            date_col: Header name of the date column.
            start:    Inclusive lower bound.
            end:      Inclusive upper bound.

        Returns:
            Filtered list of row dicts.
        """
        col = self._col(date_col)
        result = []
        for row in rows:
            d = _parse_date(row.get(col))
            if d is not None and start <= d <= end:
                result.append(row)
        return result

    def _filter_by_category(
        self,
        rows: List[Dict],
        category_col: str,
        category: str,
    ) -> List[Dict]:
        """
        Return rows whose category column exactly matches ``category``.

        Comparison is case-insensitive and strips surrounding whitespace.

        Args:
            rows:         Source row list to filter.
            category_col: Header name of the category column.
            category:     Value to match.

        Returns:
            Filtered list of row dicts.
        """
        col = self._col(category_col)
        cat = category.strip().lower()
        return [r for r in rows if str(r.get(col, "")).strip().lower() == cat]

    def _sum_col(self, rows: List[Dict], amount_col: str) -> Decimal:
        """
        Sum the numeric values in ``amount_col`` across ``rows``.

        Cells that cannot be parsed as numbers are skipped silently.

        Args:
            rows:       Row list to aggregate.
            amount_col: Header name of the amount column.

        Returns:
            ``Decimal`` total; ``Decimal("0")`` if no parseable values exist.
        """
        col = self._col(amount_col)
        total = Decimal("0")
        for row in rows:
            amt = _parse_amount(row.get(col))
            if amt is not None:
                total += amt
        return total

    # ------------------------------------------------------------------
    # 1. Sum of a column — full sheet
    # ------------------------------------------------------------------

    def sum_column(self, amount_col: str) -> Decimal:
        """
        Sum all numeric values in a column across the entire cached dataset.

        Cells that cannot be parsed as numbers (e.g. empty, text labels)
        are silently excluded.

        Args:
            amount_col: Header name of the column to sum.

        Returns:
            ``Decimal`` total.
        """
        return self._sum_col(self._rows, amount_col)

    # ------------------------------------------------------------------
    # 2. Sum of a column — date ranges
    # ------------------------------------------------------------------

    def sum_column_date_range(
        self, amount_col: str, date_col: str, start: date, end: date
    ) -> Decimal:
        """
        Sum a column for rows whose date falls within a custom range.

        Args:
            amount_col: Header name of the column to sum.
            date_col:   Header name of the date column.
            start:      Inclusive start date.
            end:        Inclusive end date.

        Returns:
            ``Decimal`` total; ``Decimal("0")`` if no rows match.
        """
        filtered = self._filter_by_date(self._rows, date_col, start, end)
        return self._sum_col(filtered, amount_col)

    def sum_column_today(self, amount_col: str, date_col: str) -> Decimal:
        """
        Sum a column for rows dated today.

        "Today" is determined by :meth:`_today`, which respects the
        ``reference_date`` override if set.

        Args:
            amount_col: Header name of the column to sum.
            date_col:   Header name of the date column.

        Returns:
            ``Decimal`` total for today's rows.
        """
        today = self._today()
        return self.sum_column_date_range(amount_col, date_col, today, today)

    def sum_column_this_week(self, amount_col: str, date_col: str) -> Decimal:
        """
        Sum a column for rows dated within the current Monday–Sunday week.

        Args:
            amount_col: Header name of the column to sum.
            date_col:   Header name of the date column.

        Returns:
            ``Decimal`` total for the current week.
        """
        today = self._today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return self.sum_column_date_range(amount_col, date_col, monday, sunday)

    def sum_column_this_month(self, amount_col: str, date_col: str) -> Decimal:
        """
        Sum a column for rows dated within the current calendar month.

        The range is from the 1st of the current month up to and including
        today (not the end of the month).

        Args:
            amount_col: Header name of the column to sum.
            date_col:   Header name of the date column.

        Returns:
            ``Decimal`` month-to-date total.
        """
        today = self._today()
        start = today.replace(day=1)
        return self.sum_column_date_range(amount_col, date_col, start, today)

    # ------------------------------------------------------------------
    # 3. Row lookup by identifier
    # ------------------------------------------------------------------

    def get_row_by_id(self, id_col: str, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Return the first row whose identifier column matches ``identifier``.

        Useful for looking up records by a GUID, order number, or any
        other unique key stored in a cell.  Comparison is case-insensitive
        and strips surrounding whitespace.

        Args:
            id_col:     Header name of the identifier column.
            identifier: Value to search for.

        Returns:
            A copy of the matching row dict, or ``None`` if not found.
        """
        col = self._col(id_col)
        target = identifier.strip().lower()
        for row in self._rows:
            if str(row.get(col, "")).strip().lower() == target:
                return dict(row)
        return None

    # ------------------------------------------------------------------
    # 4. Rows from a date range as JSON-ready list
    # ------------------------------------------------------------------

    def get_rows_date_range(
        self, date_col: str, start: date, end: date
    ) -> List[Dict[str, Any]]:
        """
        Return all rows whose date falls within ``[start, end]`` inclusive.

        Each row is returned as a plain ``dict`` keyed by header name,
        suitable for JSON serialisation or passing to a dashboard widget.

        Args:
            date_col: Header name of the date column.
            start:    Inclusive start date.
            end:      Inclusive end date.

        Returns:
            List of row dicts; empty list if no rows match.
        """
        return self._filter_by_date(self._rows, date_col, start, end)

    def get_rows_today(self, date_col: str) -> List[Dict[str, Any]]:
        """
        Return all rows dated today.

        Args:
            date_col: Header name of the date column.

        Returns:
            List of row dicts for today.
        """
        today = self._today()
        return self.get_rows_date_range(date_col, today, today)

    def get_rows_this_week(self, date_col: str) -> List[Dict[str, Any]]:
        """
        Return all rows dated within the current Monday–Sunday week.

        Args:
            date_col: Header name of the date column.

        Returns:
            List of row dicts for the current week.
        """
        today = self._today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return self.get_rows_date_range(date_col, monday, sunday)

    def get_rows_this_month(self, date_col: str) -> List[Dict[str, Any]]:
        """
        Return all rows dated from the 1st of the current month up to today.

        Args:
            date_col: Header name of the date column.

        Returns:
            List of row dicts for the current month-to-date.
        """
        today = self._today()
        start = today.replace(day=1)
        return self.get_rows_date_range(date_col, start, today)

    # ------------------------------------------------------------------
    # 5. Sum with category filter, optional date range
    # ------------------------------------------------------------------

    def sum_column_by_category(
        self,
        amount_col: str,
        category_col: str,
        category: str,
        date_col: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Decimal:
        """
        Sum a column filtered by category, with an optional date range.

        Filters are applied in order: date range first (if provided), then
        category.  Category matching is case-insensitive.

        Args:
            amount_col:   Header name of the column to sum.
            category_col: Header name of the category column.
            category:     Category value to match (case-insensitive).
            date_col:     Header name of the date column.  Required when
                          ``start`` and ``end`` are provided.
            start:        Inclusive start date for the optional date filter.
            end:          Inclusive end date for the optional date filter.

        Returns:
            ``Decimal`` total; ``Decimal("0")`` if no rows match.

        Examples:
            # Total food spend this week
            utils.sum_column_by_category(
                "Amount", "Category", "Food",
                date_col="Date", start=monday, end=sunday,
            )
        """
        rows = self._rows
        if date_col and start and end:
            rows = self._filter_by_date(rows, date_col, start, end)
        rows = self._filter_by_category(rows, category_col, category)
        return self._sum_col(rows, amount_col)

    # ------------------------------------------------------------------
    # 6. Additional utilities
    # ------------------------------------------------------------------

    def count_rows_today(self, date_col: str) -> int:
        """
        Count rows dated today.

        Args:
            date_col: Header name of the date column.

        Returns:
            Integer row count for today.
        """
        today = self._today()
        return len(self._filter_by_date(self._rows, date_col, today, today))

    def count_rows(
        self,
        date_col: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> int:
        """
        Count rows, optionally filtered by a date range.

        When called with no arguments, returns the total number of data rows
        in the cache (excluding the header).

        Args:
            date_col: Header name of the date column.  Required when
                      ``start`` and ``end`` are provided.
            start:    Inclusive start date.
            end:      Inclusive end date.

        Returns:
            Integer row count.
        """
        if date_col and start and end:
            return len(self._filter_by_date(self._rows, date_col, start, end))
        return len(self._rows)

    def get_unique_values(self, col: str) -> List[str]:
        """
        Return the sorted, unique non-empty values present in a column.

        Useful for discovering all categories, tags, or status values
        without knowing them in advance.

        Args:
            col: Header name of the column to inspect.

        Returns:
            Alphabetically sorted list of unique non-empty cell values.
        """
        key = self._col(col)
        seen = set()
        result = []
        for row in self._rows:
            v = str(row.get(key, "")).strip()
            if v and v not in seen:
                seen.add(v)
                result.append(v)
        return sorted(result)

    def group_sum_by_column(
        self,
        amount_col: str,
        group_col: str,
        date_col: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Dict[str, Decimal]:
        """
        Aggregate amount totals grouped by the values in another column.

        Returns a dict of ``{group_value: total_amount}`` sorted
        alphabetically by group value.  Rows with non-numeric amounts are
        excluded from the totals but the group key is still represented if
        at least one parseable row exists for it.

        Commonly used for per-category, per-tag, or per-month breakdowns
        in dashboard widgets.

        Args:
            amount_col: Header name of the column to sum.
            group_col:  Header name of the column to group by.
            date_col:   Header name of the date column.  Required when
                        ``start`` and ``end`` are provided.
            start:      Inclusive start date for the optional date filter.
            end:        Inclusive end date for the optional date filter.

        Returns:
            Alphabetically sorted dict of ``{group: Decimal total}``.

        Examples:
            # Spend by category for the current month
            utils.group_sum_by_column(
                "Amount", "Category",
                date_col="Date", start=first_of_month, end=today,
            )
            # → {"Bills": Decimal("1200.00"), "Food": Decimal("515.75"), ...}
        """
        rows = self._rows
        if date_col and start and end:
            rows = self._filter_by_date(rows, date_col, start, end)

        group_key = self._col(group_col)
        amt_key = self._col(amount_col)
        totals: Dict[str, Decimal] = {}
        for row in rows:
            grp = str(row.get(group_key, "")).strip()
            amt = _parse_amount(row.get(amt_key))
            if amt is not None:
                totals[grp] = totals.get(grp, Decimal("0")) + amt
        return dict(sorted(totals.items()))

    def top_n_rows(
        self,
        amount_col: str,
        n: int = 5,
        date_col: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
        descending: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Return the top N rows ranked by the value in ``amount_col``.

        Rows with non-numeric amounts are treated as zero for sorting
        purposes but are still included in the output.

        Args:
            amount_col: Header name of the column to rank by.
            n:          Maximum number of rows to return.  Defaults to 5.
            date_col:   Header name of the date column.  Required when
                        ``start`` and ``end`` are provided.
            start:      Inclusive start date for the optional date filter.
            end:        Inclusive end date for the optional date filter.
            descending: If ``True`` (default), returns the highest amounts
                        first.  Set to ``False`` for the lowest amounts.

        Returns:
            List of up to ``n`` row dicts, sorted by amount.
        """
        rows = self._rows
        if date_col and start and end:
            rows = self._filter_by_date(rows, date_col, start, end)
        col = self._col(amount_col)

        def _key(row: Dict) -> Decimal:
            return _parse_amount(row.get(col)) or Decimal("0")

        return sorted(rows, key=_key, reverse=descending)[:n]

    def average_column(
        self,
        amount_col: str,
        date_col: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Optional[Decimal]:
        """
        Return the arithmetic mean of a numeric column.

        Only cells that parse successfully as numbers contribute to the
        average; empty or non-numeric cells are ignored.

        Args:
            amount_col: Header name of the column to average.
            date_col:   Header name of the date column.  Required when
                        ``start`` and ``end`` are provided.
            start:      Inclusive start date for the optional date filter.
            end:        Inclusive end date for the optional date filter.

        Returns:
            ``Decimal`` average, or ``None`` if there are no parseable values
            in the filtered row set.
        """
        rows = self._rows
        if date_col and start and end:
            rows = self._filter_by_date(rows, date_col, start, end)
        col = self._col(amount_col)
        amounts = [_parse_amount(r.get(col)) for r in rows]
        amounts = [a for a in amounts if a is not None]
        if not amounts:
            return None
        return sum(amounts, Decimal("0")) / Decimal(len(amounts))

    def search_rows(
        self,
        col: str,
        query: str,
        partial: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Full-text search within a single column.

        All comparisons are case-insensitive.  Use ``partial=True``
        (the default) for substring matching; use ``partial=False`` for
        exact equality.

        Args:
            col:     Header name of the column to search in.
            query:   Search term.
            partial: ``True`` to match any cell that *contains* ``query``
                     as a substring; ``False`` to require an exact match.

        Returns:
            List of row dicts where the column value matches the query.
            Each dict is a shallow copy of the original row.

        Examples:
            # Rows where Description contains "cof" (e.g. "Coffee")
            utils.search_rows("Description", "cof")

            # Rows where Description is exactly "Lunch"
            utils.search_rows("Description", "Lunch", partial=False)
        """
        key = self._col(col)
        q = query.strip().lower()
        result = []
        for row in self._rows:
            v = str(row.get(key, "")).strip().lower()
            if (partial and q in v) or (not partial and q == v):
                result.append(dict(row))
        return result
