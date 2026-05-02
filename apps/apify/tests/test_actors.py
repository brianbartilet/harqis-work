import pytest
from hamcrest import assert_that, instance_of

from apps.apify.config import CONFIG
from apps.apify.references.web.api.actors import ApiServiceApifyActors
from apps.apify.references.web.api.runs import ApiServiceApifyRuns
from apps.apify.references.web.api.datasets import ApiServiceApifyDatasets


@pytest.fixture()
def actors():
    return ApiServiceApifyActors(CONFIG)


@pytest.fixture()
def runs():
    return ApiServiceApifyRuns(CONFIG)


@pytest.fixture()
def datasets():
    return ApiServiceApifyDatasets(CONFIG)


@pytest.mark.smoke
def test_list_actors(actors):
    when = actors.list_actors(my=False, limit=5)
    assert_that(when, instance_of(dict))


@pytest.mark.sanity
def test_list_my_actors(actors):
    when = actors.list_actors(my=True, limit=5)
    assert_that(when, instance_of(dict))


@pytest.mark.smoke
def test_list_runs(runs):
    when = runs.list_runs(limit=5)
    assert_that(when, instance_of(dict))


@pytest.mark.smoke
def test_list_datasets(datasets):
    when = datasets.list_datasets(limit=5)
    assert_that(when, instance_of(dict))
