import pytest
from hamcrest import assert_that, instance_of, greater_than_or_equal_to, has_key, not_none

from apps.orgo.references.web.api.workspaces import ApiServiceOrgoWorkspaces
from apps.orgo.config import CONFIG


def _require_api_key():
    if not CONFIG.app_data.get('api_key'):
        pytest.skip("ORGO_API_KEY not configured in .env/apps.env")


@pytest.fixture()
def given():
    _require_api_key()
    return ApiServiceOrgoWorkspaces(CONFIG)


@pytest.fixture()
def first_workspace_id():
    _require_api_key()
    workspaces = ApiServiceOrgoWorkspaces(CONFIG).list_workspaces()
    if isinstance(workspaces, list) and workspaces:
        return workspaces[0]['id']
    return None


@pytest.mark.smoke
@pytest.mark.skip(reason="Orgo migrated their API host away from www.orgo.ai/api/ — apps_config.yaml base_url returns 404 HTML. Re-enable once new resource paths are confirmed.")
def test_list_workspaces(given):
    """API is reachable and returns a list of workspaces."""
    _require_api_key()
    when = given.list_workspaces()
    assert_that(when, instance_of(list))
    assert_that(len(when), greater_than_or_equal_to(0))


@pytest.mark.sanity
def test_get_workspace(first_workspace_id):
    """Fetches a workspace by ID."""
    if not first_workspace_id:
        pytest.skip("No workspaces available")
    when = ApiServiceOrgoWorkspaces(CONFIG).get_workspace(first_workspace_id)
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('id'))
    assert_that(when, has_key('name'))
    assert_that(when, has_key('desktops'))
    assert_that(when.get('id'), not_none())
