import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than

from apps.github.references.web.api.repos import ApiServiceGitHubRepos
from apps.github.references.dto.github import DtoGitHubRepo, DtoGitHubIssue, DtoGitHubBranch
from apps.github.config import CONFIG


@pytest.fixture()
def svc():
    return ApiServiceGitHubRepos(CONFIG)


@pytest.mark.smoke
def test_get_authenticated_user(svc):
    result = svc.get_authenticated_user()
    assert_that(result, instance_of(dict))
    assert_that(result.get("login"), not_none())


@pytest.mark.smoke
def test_list_repos(svc):
    result = svc.list_repos(per_page=10)
    assert_that(result, instance_of(list))
    assert_that(len(result), greater_than(0))
    assert_that(result[0], instance_of(DtoGitHubRepo))
    assert_that(result[0].name, not_none())


@pytest.mark.smoke
def test_get_repo(svc):
    repos = svc.list_repos(per_page=1)
    assert repos, "No repos found"
    r = repos[0]
    owner, name = r.full_name.split("/")
    result = svc.get_repo(owner=owner, repo=name)
    assert_that(result, instance_of(DtoGitHubRepo))
    assert_that(result.full_name, not_none())


@pytest.mark.smoke
def test_list_branches(svc):
    repos = svc.list_repos(per_page=1)
    assert repos
    r = repos[0]
    owner, name = r.full_name.split("/")
    result = svc.list_branches(owner=owner, repo=name)
    assert_that(result, instance_of(list))


@pytest.mark.sanity
def test_search_repos(svc):
    result = svc.search_repos(query="language:python stars:>100", per_page=5)
    assert_that(result, instance_of(list))
    assert_that(len(result), greater_than(0))
    assert_that(result[0], instance_of(DtoGitHubRepo))
