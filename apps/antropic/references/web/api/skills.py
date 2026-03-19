from typing import Optional

from apps.antropic.references.dto.skill import DtoAnthropicSkill
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

_SKILLS_BETA_HEADER = "skills-2025-10-02"


class ApiServiceAnthropicSkills(BaseApiServiceAnthropic):
    """
    Service for interacting with the Anthropic Skills API (beta).

    Skills are reusable, versioned capability bundles that can be referenced
    in Messages API calls to extend Claude's behaviour.

    Beta header: skills-2025-10-02
    """

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @staticmethod
    def _parse_skill(data: dict) -> DtoAnthropicSkill:
        return DtoAnthropicSkill(
            id=data.get('id'),
            created_at=data.get('created_at'),
            display_title=data.get('display_title'),
            latest_version=data.get('latest_version'),
            source=data.get('source'),
            type=data.get('type', 'skill'),
            updated_at=data.get('updated_at'),
        )

    def create_skill(self, display_title: Optional[str] = None, **body_kwargs) -> DtoAnthropicSkill:
        """
        Create a new custom skill.

        Args:
            display_title: Human-readable label for the skill.
            **body_kwargs: Additional skill definition fields passed directly in the request body.

        Returns:
            DtoAnthropicSkill with the created skill's metadata.
        """
        body = {}
        if display_title:
            body['display_title'] = display_title
        body.update(body_kwargs)

        response = self.base_client.post(
            '/skills',
            body=body or None,
            cast_to=dict,
            options={'headers': {'anthropic-beta': _SKILLS_BETA_HEADER}},
        )
        return self._parse_skill(response)

    def list_skills(self) -> list[DtoAnthropicSkill]:
        """
        List all available skills (custom and Anthropic-provided).

        Returns:
            List of DtoAnthropicSkill objects.
        """
        response = self.base_client.get(
            '/skills',
            cast_to=dict,
            options={'headers': {'anthropic-beta': _SKILLS_BETA_HEADER}},
        )
        data = response.get('data', [])
        return [self._parse_skill(s) for s in data]

    def retrieve_skill(self, skill_id: str) -> DtoAnthropicSkill:
        """
        Retrieve a specific skill by ID.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            DtoAnthropicSkill with the skill's metadata.
        """
        response = self.base_client.get(
            f'/skills/{skill_id}',
            cast_to=dict,
            options={'headers': {'anthropic-beta': _SKILLS_BETA_HEADER}},
        )
        return self._parse_skill(response)
