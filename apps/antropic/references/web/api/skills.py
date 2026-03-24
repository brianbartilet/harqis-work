import io
import zipfile

import httpx

from apps.antropic.references.dto.skill import DtoAnthropicSkill
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

_SKILLS_BASE_URL = 'https://api.anthropic.com/v1/skills'
_SKILLS_BETA_HEADER = 'skills-2025-10-02'
_ANTHROPIC_VERSION = '2023-06-01'


class ApiServiceAnthropicSkills(BaseApiServiceAnthropic):
    """
    Service for interacting with the Anthropic Skills API (beta).

    Skills are reusable, versioned capability bundles that can be referenced
    in Messages API calls to extend Claude's behaviour.

    Uses httpx directly because the SDK's internal get/post deserialization
    does not handle non-standard beta endpoints reliably. All calls are wrapped
    with exponential backoff via _httpx_with_backoff.

    Beta header: skills-2025-10-02
    """

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def _headers(self) -> dict:
        return {
            'x-api-key': self.api_key,
            'anthropic-version': _ANTHROPIC_VERSION,
            'anthropic-beta': _SKILLS_BETA_HEADER,
        }

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

    def create_skill(
        self,
        name: str,
        display_title: str = '',
        description: str = '',
    ) -> DtoAnthropicSkill:
        """
        Create a new custom skill.

        Builds the required ZIP package in memory:
          {name}/
            SKILL.md   <- YAML frontmatter + body

        The ZIP buffer is rebuilt on each retry so the stream is always fresh.

        Args:
            name: Skill identifier — lowercase letters, numbers, and hyphens only.
            display_title: Human-readable label shown in the console.
            description: Short description of what the skill does.

        Returns:
            DtoAnthropicSkill with the created skill's metadata.
        """
        skill_md = f"---\nname: {name}\ndisplay_title: {display_title}\ndescription: {description}\n---\n# {display_title or name}\n"

        def _do_post():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f'{name}/SKILL.md', skill_md)
            buf.seek(0)
            return httpx.post(
                _SKILLS_BASE_URL,
                headers=self._headers(),
                files=[('files[]', ('skill.zip', buf, 'application/zip'))],
            )

        response = self._httpx_with_backoff(_do_post)
        return self._parse_skill(response.json())

    def list_skills(self) -> list[DtoAnthropicSkill]:
        """
        List all available skills (custom and Anthropic-provided).

        Returns:
            List of DtoAnthropicSkill objects.
        """
        response = self._httpx_with_backoff(
            httpx.get, _SKILLS_BASE_URL, headers=self._headers()
        )
        return [self._parse_skill(s) for s in response.json().get('data', [])]

    def retrieve_skill(self, skill_id: str) -> DtoAnthropicSkill:
        """
        Retrieve a specific skill by ID.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            DtoAnthropicSkill with the skill's metadata.
        """
        response = self._httpx_with_backoff(
            httpx.get, f'{_SKILLS_BASE_URL}/{skill_id}', headers=self._headers()
        )
        return self._parse_skill(response.json())
