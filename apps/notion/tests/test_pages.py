import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.notion.references.web.api.pages import ApiServiceNotionPages
from apps.notion.references.web.api.search import ApiServiceNotionSearch
from apps.notion.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceNotionPages(CONFIG)


@pytest.fixture()
def first_page_id():
    """Retrieve the first accessible page via search."""
    result = ApiServiceNotionSearch(CONFIG).search(filter_object='page', page_size=1)
    results = result.get('results', [])
    if results:
        return results[0]['id']
    return None


@pytest.mark.smoke
def test_get_page(given, first_page_id):
    if first_page_id is None:
        pytest.skip("No accessible pages found")
    when = given.get_page(first_page_id)
    assert_that(when, instance_of(dict))
    assert_that(when.get('id'), not_none())
    assert_that(when.get('object'), not_none())


@pytest.mark.sanity
def test_get_page_has_properties(given, first_page_id):
    if first_page_id is None:
        pytest.skip("No accessible pages found")
    when = given.get_page(first_page_id)
    assert_that(when.get('properties'), not_none())
