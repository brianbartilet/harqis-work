import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.jira.references.web.api.projects import ApiServiceJiraProjects
from apps.jira.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceJiraProjects(CONFIG)


@pytest.fixture()
def first_project_key():
    projects = ApiServiceJiraProjects(CONFIG).get_projects()
    if projects:
        return projects[0]['key']
    return None


@pytest.mark.smoke
def test_get_projects(given):
    when = given.get_projects()
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(0))


@pytest.mark.smoke
def test_get_project(given, first_project_key):
    if first_project_key is None:
        pytest.skip("No projects found")
    when = given.get_project(first_project_key)
    assert_that(when, instance_of(dict))
    assert_that(when.get('key'), not_none())
    assert_that(when.get('name'), not_none())
