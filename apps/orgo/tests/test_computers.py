import pytest
from hamcrest import assert_that, instance_of, has_key, not_none, is_in

from apps.orgo.references.web.api.workspaces import ApiServiceOrgoWorkspaces
from apps.orgo.references.web.api.computers import ApiServiceOrgoComputers
from apps.orgo.config import CONFIG

VALID_STATUSES = ('starting', 'running', 'stopping', 'stopped', 'suspended', 'error')


def _require_api_key():
    if not CONFIG.app_data.get('api_key'):
        pytest.skip("ORGO_API_KEY not configured in .env/apps.env")


@pytest.fixture()
def first_workspace_id():
    _require_api_key()
    workspaces = ApiServiceOrgoWorkspaces(CONFIG).list_workspaces()
    if isinstance(workspaces, list) and workspaces:
        return workspaces[0]['id']
    return None


@pytest.fixture()
def first_computer(first_workspace_id):
    """Returns the first computer in the first workspace, or None."""
    if not first_workspace_id:
        return None
    workspace = ApiServiceOrgoWorkspaces(CONFIG).get_workspace(first_workspace_id)
    if not workspace.get('computer_count', 0):
        return None
    # computer_count > 0 but listing requires a different endpoint — skip if no computers
    return None


@pytest.mark.smoke
def test_api_reachable(first_workspace_id):
    """Workspaces endpoint is reachable (prerequisite for computer tests)."""
    _require_api_key()
    workspaces = ApiServiceOrgoWorkspaces(CONFIG).list_workspaces()
    assert_that(workspaces, instance_of(list))


@pytest.mark.sanity
def test_get_computer_from_workspace(first_workspace_id):
    """Fetches first workspace and checks desktops (computers) field exists."""
    if not first_workspace_id:
        pytest.skip("No workspaces available")
    workspace = ApiServiceOrgoWorkspaces(CONFIG).get_workspace(first_workspace_id)
    assert_that(workspace, has_key('desktops'))
    assert_that(workspace.get('desktops'), instance_of(list))


@pytest.mark.sanity
def test_computer_status_values(first_workspace_id):
    """Computer status is one of the known enum values if a computer exists."""
    if not first_workspace_id:
        pytest.skip("No workspaces available")
    workspace = ApiServiceOrgoWorkspaces(CONFIG).get_workspace(first_workspace_id)
    desktops = workspace.get('desktops', [])
    if not desktops:
        pytest.skip("No computers in workspace — provision one to run this test")
    computer_id = desktops[0]['id']
    computer = ApiServiceOrgoComputers(CONFIG).get_computer(computer_id)
    assert_that(computer, instance_of(dict))
    assert_that(computer.get('status'), is_in(VALID_STATUSES))
