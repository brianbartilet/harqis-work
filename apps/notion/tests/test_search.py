import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.notion.references.web.api.search import ApiServiceNotionSearch
from apps.notion.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceNotionSearch(CONFIG)


@pytest.mark.smoke
def test_search_no_query(given):
    when = given.search(page_size=5)
    assert_that(when, instance_of(dict))
    assert_that(when.get('results'), instance_of(list))


@pytest.mark.smoke
def test_search_filter_pages(given):
    when = given.search(filter_object='page', page_size=5)
    assert_that(when, instance_of(dict))
    results = when.get('results', [])
    assert_that(results, instance_of(list))
    for r in results:
        assert r.get('object') == 'page'


@pytest.mark.sanity
def test_search_filter_databases(given):
    when = given.search(filter_object='database', page_size=5)
    assert_that(when, instance_of(dict))
    results = when.get('results', [])
    assert_that(results, instance_of(list))
    for r in results:
        assert r.get('object') == 'database'


@pytest.mark.sanity
def test_search_with_query(given):
    when = given.search(query='test', page_size=5)
    assert_that(when, instance_of(dict))
    assert_that(when.get('results'), instance_of(list))
