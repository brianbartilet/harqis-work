import os

import pytest
from hamcrest import assert_that, instance_of, not_none

from apps.appsheet.config import CONFIG
from apps.appsheet.references.dto.tables import DtoAppSheetActionResult
from apps.appsheet.references.web.api.tables import ApiServiceAppSheetTables


pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("APPSHEET_APPLICATION_ACCESS_KEY")
        and os.environ.get("APPSHEET_DEFAULT_APP_ID")
        and os.environ.get("APPSHEET_TEST_TABLE")
    ),
    reason=(
        "AppSheet tests need APPSHEET_APPLICATION_ACCESS_KEY, "
        "APPSHEET_DEFAULT_APP_ID, and APPSHEET_TEST_TABLE set."
    ),
)


@pytest.fixture()
def given():
    return ApiServiceAppSheetTables(CONFIG)


@pytest.fixture()
def test_table() -> str:
    return os.environ["APPSHEET_TEST_TABLE"]


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
