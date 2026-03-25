import os
import pytest
from hamcrest import assert_that, instance_of, greater_than_or_equal_to, equal_to, is_not, none

from apps.google_apps.references.web.api.sheets import ApiServiceGoogleSheets, SheetInputOption
from apps.apps_config import CONFIG_MANAGER

# Set SHEETS_WRITE_ENABLED=1 in .env/apps.env once the sheet grants editor access
# to the credentials.json OAuth user.
_write_enabled = os.environ.get("SHEETS_WRITE_ENABLED", "0") == "1"
skip_write = pytest.mark.skipif(not _write_enabled, reason="Sheet is read-only for this OAuth user — set SHEETS_WRITE_ENABLED=1 to run write tests")

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# No sheet-name prefix — defaults to first tab regardless of its name.
# Write tests target column Z to avoid overwriting real data.
_TEST_RANGE = "A1:C3"
_TEST_CELL = "Z1"


@pytest.fixture()
def given():
    config = CONFIG_MANAGER.get("GOOGLE_APPS")
    config.app_data["sheet_id"] = config.app_data["sheet_id_app_harqis"]
    # BaseApiServiceGoogle reads scopes from app_data (not the scopes_list kwarg).
    # Use a separate storage file so sheets scope does not overwrite the calendar
    # token used by other Google Apps tests.
    # NOTE: first run will open a browser for OAuth consent — grant Sheets access.
    config.app_data["scopes"] = _SCOPES
    config.app_data["storage"] = "storage_sheets.json"
    service = ApiServiceGoogleSheets(config, scopes_list=_SCOPES)
    return service


# ─────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test__get_values__returns_list(given):
    when = given.get_values(_TEST_RANGE)

    assert_that(when, instance_of(list))


@pytest.mark.smoke
def test__get_values__sheet_id_is_set(given):
    assert_that(given.sheet_id, is_not(none()))


# ─────────────────────────────────────────────────────────────
# Write / update
# ─────────────────────────────────────────────────────────────

@skip_write
@pytest.mark.sanity
def test__update_values__raw(given):
    values = [["test_u", "test_v", "test_w"]]
    when = given.update_values(_TEST_CELL, values, SheetInputOption.RAW)

    assert_that(when.get("updatedCells"), greater_than_or_equal_to(1))


@skip_write
@pytest.mark.sanity
def test__update_values__user_entered(given):
    values = [["=1+1"]]
    when = given.update_values(_TEST_CELL, values, SheetInputOption.USER_ENTERED)

    assert_that(when.get("updatedCells"), greater_than_or_equal_to(1))


# ─────────────────────────────────────────────────────────────
# Clear
# ─────────────────────────────────────────────────────────────

@skip_write
@pytest.mark.sanity
def test__clear_values__returns_cleared_range(given):
    when = given.clear_values(_TEST_CELL)

    assert_that(when.get("clearedRange"), is_not(none()))


# ─────────────────────────────────────────────────────────────
# Buffer helpers
# ─────────────────────────────────────────────────────────────

@skip_write
@pytest.mark.smoke
def test__buffer__add_row_and_flush(given):
    given.set_headers(["col_a", "col_b", "col_c"])
    given.add_row(["val_1", "val_2", "val_3"])
    given.add_row(["val_4", "val_5", "val_6"])

    assert_that(len(given.row_data), equal_to(3))  # header + 2 rows

    when = given.flush_buffer(_TEST_CELL)

    assert_that(when.get("updatedCells"), greater_than_or_equal_to(1))


@pytest.mark.smoke
def test__buffer__set_rows_replaces_buffer(given):
    given.set_headers(["h1", "h2"])
    given.set_rows([["a", "b"], ["c", "d"]])

    # set_rows resets, so only 2 rows (no header)
    assert_that(len(given.row_data), equal_to(2))


@pytest.mark.smoke
def test__buffer__reset_clears_data(given):
    given.add_row(["x", "y"])
    given.reset_buffer()

    assert_that(len(given.row_data), equal_to(0))
