import pytest
from hamcrest import assert_that, instance_of, has_key, not_none

from apps.apps_config import CONFIG_MANAGER
from apps.google_apps.references.web.api.tasks import ApiServiceGoogleTasks


@pytest.fixture()
def given():
    return ApiServiceGoogleTasks(CONFIG_MANAGER.get("GOOGLE_TASKS"))


@pytest.mark.smoke
def test_list_task_lists(given):
    """Task lists endpoint is reachable — confirms OAuth token is valid."""
    when = given.list_task_lists()
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_get_default_task_list(given):
    """Fetches the default task list."""
    when = given.get_task_list('@default')
    assert_that(when, instance_of(dict))
    assert_that(when, has_key('id'))
    assert_that(when, has_key('title'))


@pytest.mark.sanity
def test_list_tasks_default(given):
    """Lists tasks in the default task list."""
    when = given.list_tasks('@default', show_completed=False)
    assert_that(when, instance_of(list))


@pytest.mark.sanity
def test_list_all_tasks(given):
    """Lists all tasks across all task lists."""
    when = given.list_all_tasks()
    assert_that(when, instance_of(list))
