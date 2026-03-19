import pytest

from hamcrest import assert_that, not_none, instance_of

from apps.antropic.config import CONFIG
from apps.antropic.references.dto.skill import DtoAnthropicSkill
from apps.antropic.references.web.api.skills import ApiServiceAnthropicSkills


@pytest.fixture()
def given_service():
    return ApiServiceAnthropicSkills(CONFIG)


@pytest.mark.smoke
def test_skills_service_initializes(given_service):
    assert_that(given_service.base_client, not_none())


@pytest.mark.sanity
def test_list_skills_returns_list(given_service):
    result = given_service.list_skills()

    assert_that(result, not_none())
    assert_that(isinstance(result, list), True)


@pytest.mark.sanity
def test_create_skill_returns_dto(given_service):
    result = given_service.create_skill(
        name='harqis-test-skill',
        display_title='Harqis Test Skill',
        description='Integration test skill for harqis-work.',
    )

    assert_that(result, instance_of(DtoAnthropicSkill))
    assert_that(result.id, not_none())
    assert_that(result.type, not_none())
