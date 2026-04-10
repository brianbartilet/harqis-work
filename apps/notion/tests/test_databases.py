import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.notion.references.web.api.databases import ApiServiceNotionDatabases
from apps.notion.references.web.api.search import ApiServiceNotionSearch
from apps.notion.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceNotionDatabases(CONFIG)


@pytest.fixture()
def first_database_id():
    """Retrieve the first accessible database via search."""
    result = ApiServiceNotionSearch(CONFIG).search(filter_object='database', page_size=1)
    results = result.get('results', [])
    if results:
        return results[0]['id']
    return None


@pytest.mark.smoke
def test_search_for_database(first_database_id):
    assert first_database_id is not None, "No databases found — check integration permissions"


@pytest.mark.smoke
def test_get_database(given, first_database_id):
    if first_database_id is None:
        pytest.skip("No accessible databases found")
    when = given.get_database(first_database_id)
    assert_that(when, instance_of(dict))
    assert_that(when.get('id'), not_none())
    assert_that(when.get('object'), not_none())


@pytest.mark.sanity
def test_query_database(given, first_database_id):
    if first_database_id is None:
        pytest.skip("No accessible databases found")
    when = given.query_database(first_database_id, page_size=10)
    assert_that(when, instance_of(dict))
    assert_that(when.get('results'), instance_of(list))


@pytest.mark.sanity
def test_query_database_with_sort(given, first_database_id):
    if first_database_id is None:
        pytest.skip("No accessible databases found")
    sorts = [{'timestamp': 'last_edited_time', 'direction': 'descending'}]
    when = given.query_database(first_database_id, sorts=sorts, page_size=5)
    assert_that(when, instance_of(dict))
    assert_that(when.get('results'), instance_of(list))
