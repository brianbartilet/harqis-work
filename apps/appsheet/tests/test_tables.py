import os

import pytest
from hamcrest import assert_that, has_length, greater_than, instance_of, not_none, only_contains

from apps.appsheet.config import CONFIG
from apps.appsheet.references.dto.tables import DtoAppSheetActionResult
from apps.appsheet.references.web.api.tables import ApiServiceAppSheetTables


pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("APPSHEET_APPLICATION_ACCESS_KEY")
        and os.environ.get("APPSHEET_DEFAULT_APP_ID")
        and os.environ.get("APPSHEET_DEFAULT_TABLE")
    ),
    reason=(
        "AppSheet tests need APPSHEET_APPLICATION_ACCESS_KEY, "
        "APPSHEET_DEFAULT_APP_ID, and APPSHEET_DEFAULT_TABLE set."
    ),
)


@pytest.fixture()
def given():
    return ApiServiceAppSheetTables(CONFIG)


@pytest.fixture()
def test_table(given) -> str:
    return given.default_table


@pytest.mark.smoke
def test_find_rows_returns_list(given, test_table):
    when = given.find_rows(table=test_table)
    assert_that(when, instance_of(DtoAppSheetActionResult))
    assert_that(when.rows, not_none())


@pytest.mark.sanity
def test_find_rows_with_selector(given, test_table):
    when = given.find_rows(
        table=test_table,
        selector=f'Filter("{test_table}", TRUE)',
    )
    assert_that(when.rows, not_none())


@pytest.mark.smoke
def test_get_headers_returns_user_columns(given, test_table):
    when = given.get_headers(table=test_table)
    assert_that(when, instance_of(list))
    assert_that(when, has_length(greater_than(0)))
    assert_that([k.startswith("_") for k in when], only_contains(False))
