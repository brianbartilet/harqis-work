import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.jira.references.web.api.issues import ApiServiceJiraIssues
from apps.jira.references.web.api.projects import ApiServiceJiraProjects
from apps.jira.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceJiraIssues(CONFIG)


@pytest.fixture()
def first_project_key():
    projects = ApiServiceJiraProjects(CONFIG).get_projects()
    if projects:
        return projects[0]['key']
    return None


@pytest.fixture()
def first_issue_key(first_project_key):
    if first_project_key is None:
        return None
    result = ApiServiceJiraIssues(CONFIG).search_issues(
        jql=f'project={first_project_key} ORDER BY created DESC',
        max_results=1
    )
    issues = result.get('issues', []) if isinstance(result, dict) else []
    if issues:
        return issues[0]['key']
    return None


@pytest.mark.smoke
def test_search_issues(given, first_project_key):
    if first_project_key is None:
        pytest.skip("No projects found")
    when = given.search_issues(jql=f'project={first_project_key}', max_results=10)
    assert_that(when, instance_of(dict))
    assert_that(when.get('issues'), not_none())


@pytest.mark.smoke
def test_get_issue(given, first_issue_key):
    if first_issue_key is None:
        pytest.skip("No issues found")
    when = given.get_issue(first_issue_key)
    assert_that(when, instance_of(dict))
    assert_that(when.get('key'), not_none())
    assert_that(when.get('fields'), not_none())


@pytest.mark.sanity
def test_get_issue_comments(given, first_issue_key):
    if first_issue_key is None:
        pytest.skip("No issues found")
    when = given.get_issue_comments(first_issue_key)
    assert_that(when, instance_of(dict))
