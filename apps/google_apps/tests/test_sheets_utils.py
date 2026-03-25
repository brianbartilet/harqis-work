"""
Tests for SpreadsheetUtils.

Two fixture tiers:
  - `utils_live`  — hits the real Google Sheet (requires valid OAuth token).
                    Skipped if SHEETS_UTILS_LIVE=1 is not set in .env/apps.env.
  - `utils`       — uses an injected in-memory dataset; always runs, no auth needed.

Column layout assumed for the sample sheet:
    Date | ID | Category | Description | Amount
"""

import os
import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from hamcrest import assert_that, equal_to, instance_of, greater_than_or_equal_to, none, is_not, has_length, contains_inanyorder

from apps.google_apps.references.web.api.sheets_utils import SpreadsheetUtils
from apps.google_apps.references.web.api.sheets import ApiServiceGoogleSheets
from apps.apps_config import CONFIG_MANAGER

# ─────────────────────────────────────────────────────────────
# Sample sheet config
# ─────────────────────────────────────────────────────────────

_SAMPLE_SHEET_ID = "1o3mrRl92k9DDCgK1YSP_yq84_gZhWEriI4OVG_S9La4"
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

_DATE_COL = "Date"
_ID_COL = "ID"
_CATEGORY_COL = "Category"
_AMOUNT_COL = "Amount"

_live_enabled = os.environ.get("SHEETS_UTILS_LIVE", "0") == "1"
skip_live = pytest.mark.skipif(not _live_enabled, reason="Live sheet test — set SHEETS_UTILS_LIVE=1 to run")

# ─────────────────────────────────────────────────────────────
# In-memory fixture — pinned to a fixed reference date so tests
# never break due to day-of-week edge cases
# ─────────────────────────────────────────────────────────────

# Pin to a known Wednesday so Mon/Tue/Wed are clearly "earlier this week"
_REF_DATE = date(2026, 3, 25)          # Wednesday
_REF_MONDAY = date(2026, 3, 23)        # Monday of that week
_LAST_MONDAY = date(2026, 3, 16)       # previous Monday

_SAMPLE_ROWS = [
    # headers
    ["Date", "ID", "Category", "Description", "Amount"],
    # this week — Mon/Tue/Wed
    ["2026-03-23", "uuid-001", "Food",      "Lunch",          "150.00"],
    ["2026-03-24", "uuid-002", "Transport", "Grab",           "80.50"],
    ["2026-03-24", "uuid-003", "Food",      "Coffee",         "45.00"],
    # today (Wed 2026-03-25)
    ["2026-03-25", "uuid-004", "Bills",     "Electric",       "1200.00"],
    ["2026-03-25", "uuid-005", "Food",      "Dinner",         "320.75"],
    # last week
    ["2026-03-18", "uuid-006", "Food",      "Groceries",      "850.00"],
    ["2026-03-19", "uuid-007", "Transport", "Taxi",           "95.00"],
    # bad / empty rows
    ["",           "uuid-008", "Food",      "No date",        "50.00"],
    ["2026-03-25", "uuid-009", "Bills",     "No amount",      ""],
]


@pytest.fixture()
def utils():
    """SpreadsheetUtils loaded with in-memory sample data — no auth required."""
    mock_service = MagicMock(spec=ApiServiceGoogleSheets)
    mock_service.get_values.return_value = _SAMPLE_ROWS
    su = SpreadsheetUtils(mock_service, data_range="A:E", reference_date=_REF_DATE)
    su.load()
    return su


# ─────────────────────────────────────────────────────────────
# Live fixture — real Google Sheet
# ─────────────────────────────────────────────────────────────

@pytest.fixture()
def utils_live():
    config = CONFIG_MANAGER.get("GOOGLE_APPS")
    config.app_data["sheet_id"] = _SAMPLE_SHEET_ID
    config.app_data["scopes"] = _SCOPES
    config.app_data["storage"] = "storage_sheets_utils.json"
    service = ApiServiceGoogleSheets(config, scopes_list=_SCOPES)
    su = SpreadsheetUtils(service, data_range="A:Z")
    su.load()
    return su


# ═════════════════════════════════════════════════════════════
# Unit tests (in-memory fixture)
# ═════════════════════════════════════════════════════════════

# ─── Headers / records ────────────────────────────────────────

@pytest.mark.smoke
def test__headers__detected(utils):
    assert_that(utils.headers, equal_to(["Date", "ID", "Category", "Description", "Amount"]))


@pytest.mark.smoke
def test__records__count_excludes_header(utils):
    # 9 data rows in _SAMPLE_ROWS (header excluded)
    assert_that(len(utils.records), equal_to(len(_SAMPLE_ROWS) - 1))


# ─── 1. sum_column (full sheet) ───────────────────────────────

@pytest.mark.smoke
def test__sum_column__includes_all_parseable_amounts(utils):
    expected = Decimal("150.00") + Decimal("80.50") + Decimal("45.00") + \
               Decimal("1200.00") + Decimal("320.75") + \
               Decimal("850.00") + Decimal("95.00") + Decimal("50.00")
    # uuid-009 has no amount — excluded
    assert_that(utils.sum_column(_AMOUNT_COL), equal_to(expected))


# ─── 2. sum_column_today ─────────────────────────────────────

@pytest.mark.smoke
def test__sum_column_today__only_todays_rows(utils):
    # ref today = 2026-03-25: uuid-004 (1200), uuid-005 (320.75) — uuid-009 has no amount
    expected = Decimal("1200.00") + Decimal("320.75")
    assert_that(utils.sum_column_today(_AMOUNT_COL, _DATE_COL), equal_to(expected))


# ─── 2. sum_column_this_week ─────────────────────────────────

@pytest.mark.smoke
def test__sum_column_this_week__only_current_week(utils):
    # This week (Mon 23 – Sun 29 Mar): uuid-001..005 (uuid-009 no amount, uuid-006/007 last week)
    expected = Decimal("150.00") + Decimal("80.50") + Decimal("45.00") + \
               Decimal("1200.00") + Decimal("320.75")
    assert_that(utils.sum_column_this_week(_AMOUNT_COL, _DATE_COL), equal_to(expected))


# ─── 2. sum_column_date_range ────────────────────────────────

@pytest.mark.smoke
def test__sum_column_date_range__custom_range(utils):
    start = _REF_MONDAY
    end = _REF_MONDAY + timedelta(days=1)   # Mon–Tue: uuid-001 (150), uuid-002 (80.50), uuid-003 (45)
    expected = Decimal("150.00") + Decimal("80.50") + Decimal("45.00")
    assert_that(utils.sum_column_date_range(_AMOUNT_COL, _DATE_COL, start, end), equal_to(expected))


@pytest.mark.smoke
def test__sum_column_date_range__empty_range_returns_zero(utils):
    future = _REF_DATE + timedelta(days=365)
    result = utils.sum_column_date_range(_AMOUNT_COL, _DATE_COL, future, future)
    assert_that(result, equal_to(Decimal("0")))


# ─── 3. get_row_by_id ────────────────────────────────────────

@pytest.mark.smoke
def test__get_row_by_id__found(utils):
    row = utils.get_row_by_id(_ID_COL, "uuid-003")
    assert_that(row, is_not(none()))
    assert_that(row["Description"], equal_to("Coffee"))
    assert_that(row["Category"], equal_to("Food"))


@pytest.mark.smoke
def test__get_row_by_id__case_insensitive(utils):
    row = utils.get_row_by_id(_ID_COL, "UUID-003")
    assert_that(row, is_not(none()))


@pytest.mark.smoke
def test__get_row_by_id__not_found_returns_none(utils):
    assert_that(utils.get_row_by_id(_ID_COL, "uuid-999"), none())


# ─── 4. get_rows_date_range ──────────────────────────────────

@pytest.mark.smoke
def test__get_rows_date_range__returns_correct_rows(utils):
    rows = utils.get_rows_date_range(_DATE_COL, _REF_MONDAY, _REF_MONDAY)
    # Only uuid-001 is on Mon 2026-03-23
    assert_that(rows, has_length(1))
    assert_that(rows[0]["ID"], equal_to("uuid-001"))


@pytest.mark.smoke
def test__get_rows_today__returns_correct_rows(utils):
    rows = utils.get_rows_today(_DATE_COL)
    ids = [r["ID"] for r in rows]
    # ref today = 2026-03-25: uuid-004, uuid-005, uuid-009
    assert_that(set(ids), equal_to({"uuid-004", "uuid-005", "uuid-009"}))


@pytest.mark.smoke
def test__get_rows_this_week__excludes_last_week(utils):
    rows = utils.get_rows_this_week(_DATE_COL)
    ids = [r["ID"] for r in rows]
    assert "uuid-006" not in ids
    assert "uuid-007" not in ids


# ─── 5. sum_column_by_category ───────────────────────────────

@pytest.mark.smoke
def test__sum_by_category__food_all_time(utils):
    # Food rows with amounts: uuid-001 (150), uuid-003 (45), uuid-005 (320.75), uuid-006 (850), uuid-008 (50)
    expected = Decimal("150.00") + Decimal("45.00") + Decimal("320.75") + Decimal("850.00") + Decimal("50.00")
    result = utils.sum_column_by_category(_AMOUNT_COL, _CATEGORY_COL, "Food")
    assert_that(result, equal_to(expected))


@pytest.mark.smoke
def test__sum_by_category__food_this_week(utils):
    # Food this week (Mon 23 – Sun 29): uuid-001 (150), uuid-003 (45), uuid-005 (320.75)
    expected = Decimal("150.00") + Decimal("45.00") + Decimal("320.75")
    result = utils.sum_column_by_category(
        _AMOUNT_COL, _CATEGORY_COL, "Food",
        date_col=_DATE_COL, start=_REF_MONDAY, end=_REF_MONDAY + timedelta(days=6)
    )
    assert_that(result, equal_to(expected))


@pytest.mark.smoke
def test__sum_by_category__unknown_category_returns_zero(utils):
    result = utils.sum_column_by_category(_AMOUNT_COL, _CATEGORY_COL, "Unicorn")
    assert_that(result, equal_to(Decimal("0")))


@pytest.mark.smoke
def test__sum_by_category__case_insensitive(utils):
    lower = utils.sum_column_by_category(_AMOUNT_COL, _CATEGORY_COL, "food")
    upper = utils.sum_column_by_category(_AMOUNT_COL, _CATEGORY_COL, "FOOD")
    assert_that(lower, equal_to(upper))


# ─── 6. Additional utilities ─────────────────────────────────

@pytest.mark.smoke
def test__count_rows__total(utils):
    assert_that(utils.count_rows(), equal_to(len(_SAMPLE_ROWS) - 1))


@pytest.mark.smoke
def test__count_rows__date_range(utils):
    count = utils.count_rows(date_col=_DATE_COL, start=_REF_DATE, end=_REF_DATE)
    assert_that(count, equal_to(3))   # uuid-004, uuid-005, uuid-009


@pytest.mark.smoke
def test__get_unique_values__categories(utils):
    cats = utils.get_unique_values(_CATEGORY_COL)
    assert_that(set(cats), equal_to({"Bills", "Food", "Transport"}))


@pytest.mark.smoke
def test__group_sum_by_column__by_category(utils):
    result = utils.group_sum_by_column(_AMOUNT_COL, _CATEGORY_COL)
    assert_that(result["Food"], equal_to(
        Decimal("150.00") + Decimal("45.00") + Decimal("320.75") + Decimal("850.00") + Decimal("50.00")
    ))
    assert_that(result["Transport"], equal_to(Decimal("80.50") + Decimal("95.00")))
    assert_that(result["Bills"], equal_to(Decimal("1200.00")))


@pytest.mark.smoke
def test__group_sum_by_column__date_filtered(utils):
    result = utils.group_sum_by_column(
        _AMOUNT_COL, _CATEGORY_COL,
        date_col=_DATE_COL, start=_REF_MONDAY, end=_REF_MONDAY + timedelta(days=6)
    )
    assert "Food" in result
    # Last week's Food rows should not be included
    assert_that(result["Food"], equal_to(
        Decimal("150.00") + Decimal("45.00") + Decimal("320.75")
    ))


@pytest.mark.smoke
def test__top_n_rows__returns_highest_amounts(utils):
    top = utils.top_n_rows(_AMOUNT_COL, n=2)
    assert_that(top, has_length(2))
    assert_that(top[0]["ID"], equal_to("uuid-004"))  # 1200 is highest
    assert_that(top[1]["ID"], equal_to("uuid-006"))  # 850 is second


@pytest.mark.smoke
def test__average_column__all_rows(utils):
    result = utils.average_column(_AMOUNT_COL)
    assert_that(result, instance_of(Decimal))
    assert_that(result, greater_than_or_equal_to(Decimal("0")))


@pytest.mark.smoke
def test__average_column__empty_date_range_returns_none(utils):
    future = _REF_DATE + timedelta(days=365)
    result = utils.average_column(_AMOUNT_COL, date_col=_DATE_COL, start=future, end=future)
    assert_that(result, none())


@pytest.mark.smoke
def test__search_rows__partial_match(utils):
    rows = utils.search_rows("Description", "cof")
    assert_that(rows, has_length(1))
    assert_that(rows[0]["ID"], equal_to("uuid-003"))


@pytest.mark.smoke
def test__search_rows__exact_match(utils):
    rows = utils.search_rows("Description", "Lunch", partial=False)
    assert_that(rows, has_length(1))
    assert_that(rows[0]["ID"], equal_to("uuid-001"))


@pytest.mark.smoke
def test__search_rows__no_match_returns_empty(utils):
    assert_that(utils.search_rows("Description", "xyz-not-found"), has_length(0))


@pytest.mark.smoke
def test__unknown_column__raises_key_error(utils):
    with pytest.raises(KeyError, match="Column 'Nonexistent'"):
        utils.sum_column("Nonexistent")


# ═════════════════════════════════════════════════════════════
# Live integration tests (real Google Sheet)
# ═════════════════════════════════════════════════════════════

@skip_live
@pytest.mark.smoke
def test__live__loads_headers(utils_live):
    assert_that(len(utils_live.headers), greater_than_or_equal_to(1))


@skip_live
@pytest.mark.smoke
def test__live__records_is_list(utils_live):
    assert_that(utils_live.records, instance_of(list))


@skip_live
@pytest.mark.smoke
def test__live__get_unique_categories(utils_live):
    # Adjust the column name to match your actual sheet header
    cats = utils_live.get_unique_values(_CATEGORY_COL)
    assert_that(cats, instance_of(list))


@skip_live
@pytest.mark.smoke
def test__live__sum_column_this_week(utils_live):
    result = utils_live.sum_column_this_week(_AMOUNT_COL, _DATE_COL)
    assert_that(result, instance_of(Decimal))


@skip_live
@pytest.mark.smoke
def test__live__group_sum_by_category(utils_live):
    result = utils_live.group_sum_by_column(_AMOUNT_COL, _CATEGORY_COL)
    assert_that(result, instance_of(dict))
