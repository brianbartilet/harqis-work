"""
Tests for the clarify-feature skill wiring.

Verifies that:
  - The feature-clarification gate is present in the agent system prompts
    (kanban_agent_default.md, agent_code.yaml, agent_full.yaml).
  - The gate correctly identifies feature-intent trigger phrases.
  - The gate correctly identifies scaffolding-command exclusions.
  - The `skip:clarify` label escape hatch is honoured.
  - The SKILL.md documents the correct do-not-fire list.
  - The clarify-feature SKILL.md covers all required protocol steps.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.projects.agent.base import BaseKanbanAgent
from agents.projects.agent.question import (
    AgentPausedForQuestion,
    QUESTION_MARKER,
)
from agents.projects.trello.models import KanbanCard


# ── Fixtures ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent.parent
SKILL_MD = REPO_ROOT / ".claude" / "skills" / "clarify-feature" / "SKILL.md"
KANBAN_PROMPT = REPO_ROOT / "agents" / "prompts" / "kanban_agent_default.md"
PROFILES_DIR = REPO_ROOT / "agents" / "projects" / "profiles" / "examples"


# ── SKILL.md presence & structure ────────────────────────────────────────────

class TestSkillMdStructure:
    """The SKILL.md is the canonical spec — verify it covers all required areas."""

    def test_skill_md_exists(self):
        assert SKILL_MD.exists(), f"Expected SKILL.md at {SKILL_MD}"

    def test_skill_md_has_frontmatter_name(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "name: clarify-feature" in text

    def test_skill_md_has_description_field(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "description:" in text

    def test_skill_md_lists_trigger_phrases(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        # Spot-check a few canonical trigger phrases
        for phrase in ("add a feature", "new feature", "implement", "enhance"):
            assert phrase in text, f"Expected trigger phrase '{phrase}' in SKILL.md"

    def test_skill_md_lists_do_not_fire_skills(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for skill in (
            "create-new-workflow",
            "create-new-service-app",
            "create-new-hud",
            "create-new-n8n-workflow",
            "create-new-kanban-profile",
        ):
            assert skill in text, f"Expected excluded skill '{skill}' in SKILL.md"

    def test_skill_md_documents_skip_clarify_label(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "skip:clarify" in text

    def test_skill_md_has_all_protocol_steps(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for step in ("Step 0", "Step 1", "Step 2", "Step 3", "Step 4", "Step 5"):
            assert step in text, f"Missing '{step}' in SKILL.md"

    def test_skill_md_has_question_categories(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for cat in ("Category A", "Category B", "Category C", "Category D",
                    "Category E", "Category F"):
            assert cat in text, f"Missing '{cat}' in SKILL.md"

    def test_skill_md_has_spec_template(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "Feature Spec —" in text
        assert "Acceptance criteria" in text
        assert "Open questions" in text

    def test_skill_md_has_sign_off_prompt(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "Does this match your intent?" in text

    def test_skill_md_has_hard_rules(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "Hard rules" in text
        assert "No code before sign-off" in text


# ── System prompt gate presence ───────────────────────────────────────────────

class TestSystemPromptGate:
    """The gate must be present in every agent system prompt that handles code work."""

    def test_kanban_default_prompt_has_clarification_gate(self):
        text = KANBAN_PROMPT.read_text(encoding="utf-8")
        assert "Feature clarification gate" in text

    def test_kanban_default_prompt_lists_scaffold_exclusions(self):
        text = KANBAN_PROMPT.read_text(encoding="utf-8")
        for skill in ("/create-new-workflow", "/create-new-service-app"):
            assert skill in text, (
                f"Expected scaffold exclusion '{skill}' in kanban_agent_default.md"
            )

    def test_kanban_default_prompt_mentions_skip_clarify_label(self):
        text = KANBAN_PROMPT.read_text(encoding="utf-8")
        assert "skip:clarify" in text

    def test_kanban_default_prompt_instructs_ask_human(self):
        text = KANBAN_PROMPT.read_text(encoding="utf-8")
        assert "ask_human" in text

    def test_kanban_default_prompt_no_code_before_sign_off(self):
        text = KANBAN_PROMPT.read_text(encoding="utf-8")
        # Must say something about waiting / not writing before approval.
        # Accept multiple phrasings (plain text, or markdown **bold** wrapper).
        assert any(phrase in text for phrase in (
            "do NOT write",
            "do not write",
            "Do NOT write",
            "Do **not** write",
            "do **not** write",
            "not write, scaffold",
        )), "Default prompt should instruct agent not to write files before approval"

    def test_agent_code_yaml_system_prompt_has_gate(self):
        text = (PROFILES_DIR / "agent_code.yaml").read_text(encoding="utf-8")
        assert "Feature clarification gate" in text

    def test_agent_code_yaml_system_prompt_lists_exclusions(self):
        text = (PROFILES_DIR / "agent_code.yaml").read_text(encoding="utf-8")
        for skill in ("/create-new-workflow", "/create-new-service-app"):
            assert skill in text

    def test_agent_code_yaml_system_prompt_mentions_skip_clarify(self):
        text = (PROFILES_DIR / "agent_code.yaml").read_text(encoding="utf-8")
        assert "skip:clarify" in text

    def test_agent_full_yaml_system_prompt_has_gate(self):
        text = (PROFILES_DIR / "agent_full.yaml").read_text(encoding="utf-8")
        assert "Feature clarification gate" in text

    def test_agent_full_yaml_system_prompt_mentions_skip_clarify(self):
        text = (PROFILES_DIR / "agent_full.yaml").read_text(encoding="utf-8")
        assert "skip:clarify" in text


# ── Gate logic (unit-level) ───────────────────────────────────────────────────

# These helpers mirror the heuristic the agent is instructed to apply.
# They let us assert the classification logic in isolation without running
# a full Claude loop.

_SCAFFOLD_SKILL_KEYWORDS = frozenset({
    "/create-new-workflow",
    "/create-new-service-app",
    "/create-new-app-service",
    "/create-new-hud",
    "/create-new-n8n-workflow",
    "/create-new-kanban-profile",
    "/commit",
    "/deploy-harqis",
    "/run-tests",
})

_FEATURE_TRIGGER_PHRASES = (
    "add a feature",
    "i want to",
    "build me",
    "implement",
    "new feature",
    "requirements for",
    "can you add",
    "i need a",
    "feature request",
    "enhance",
    "extend",
    "update x to also",
    "make x do",
)


def _needs_clarification(card_description: str, card_labels: list[str]) -> bool:
    """Mirrors the gate logic the agent system prompt describes."""
    if "skip:clarify" in card_labels:
        return False
    desc_lower = card_description.lower()
    if any(kw in desc_lower for kw in _SCAFFOLD_SKILL_KEYWORDS):
        return False
    return any(phrase in desc_lower for phrase in _FEATURE_TRIGGER_PHRASES)


class TestGateLogic:
    """Unit tests for the classification heuristic the prompts encode."""

    @pytest.mark.parametrize("description", [
        "Add a feature to post daily summaries to Discord",
        "I want to extend the YNAB workflow to handle multi-currency",
        "Build me a retry mechanism for failed Trello comment posts",
        "New feature: show live equity curve on the HUD",
        "Can you add rate-limit handling to the Oanda client?",
        "Implement a webhook receiver for Stripe events",
        "Requirements for a Jira → Trello sync feature",
        "Enhance the orchestrator to support priority queues",
    ])
    def test_feature_descriptions_need_clarification(self, description: str):
        assert _needs_clarification(description, []) is True, (
            f"Expected '{description}' to trigger clarification"
        )

    @pytest.mark.parametrize("description", [
        "/create-new-workflow finance fetch OANDA rates",
        "/create-new-service-app stripe https://stripe.com/docs/api",
        "/create-new-hud PORTFOLIO daily equity update",
        "/create-new-n8n-workflow Slack alert on Jira ticket",
        "/create-new-kanban-profile finance",
        "/commit",
        "/deploy-harqis host",
        "/run-tests apps/trello",
        "Run the test suite for agents/projects/tests",
        "Get my open Jira tickets",
    ])
    def test_scaffold_and_utility_commands_skip_clarification(self, description: str):
        assert _needs_clarification(description, []) is False, (
            f"Expected '{description}' to skip clarification"
        )

    def test_skip_clarify_label_overrides_feature_description(self):
        """Even a clear feature description is skipped when skip:clarify is present."""
        assert _needs_clarification(
            "Add a feature to post daily summaries", ["skip:clarify"]
        ) is False

    def test_skip_clarify_among_other_labels(self):
        assert _needs_clarification(
            "Implement rate limiting", ["agent:code", "skip:clarify", "os:any"]
        ) is False

    def test_feature_description_with_non_skip_labels_still_triggers(self):
        assert _needs_clarification(
            "Enhance the Trello adapter to cache list IDs",
            ["agent:code", "os:any"],
        ) is True


# ── Agent integration: ask_human is called for feature cards ──────────────────

def _make_tool_response(tool_name: str, tool_input: dict, tool_id: str = "tu_1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "tool_use"
    return response


def _make_text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    return response


def _make_feature_card(description: str, labels: list[str] | None = None) -> KanbanCard:
    return KanbanCard(
        id="card_feature_001",
        title="Feature request",
        description=description,
        labels=labels or ["agent:code"],
        assignees=[],
        column="Ready",
        url="https://trello.com/c/card_feature_001",
    )


class TestAgentAskHumanOnFeatureCard:
    """The agent should call ask_human when processing a genuine feature card."""

    def test_agent_pauses_and_asks_question_on_feature_card(self, open_profile):
        """Agent calls ask_human (pauses) when given a new feature description."""
        provider = MagicMock()
        card = _make_feature_card(
            "Add a feature to automatically post Trello card summaries to Discord"
        )

        tool_response = _make_tool_response(
            "ask_human",
            {"question": "Can you clarify the scope of this feature?"},
        )

        with patch("anthropic.Anthropic") as mock_anthropic:
            client = MagicMock()
            mock_anthropic.return_value = client
            client.messages.create.return_value = tool_response

            agent = BaseKanbanAgent(
                profile=open_profile,
                card=card,
                provider=provider,
                api_key="test",
            )
            with pytest.raises(AgentPausedForQuestion) as exc_info:
                agent.run()

        assert exc_info.value.question == "Can you clarify the scope of this feature?"
        provider.add_comment.assert_called_once()
        comment_body = provider.add_comment.call_args[0][1]
        assert comment_body.startswith(QUESTION_MARKER)

    def test_agent_resumes_and_continues_after_clarification(self, open_profile):
        """After clarification reply, the agent picks up and completes the task."""
        provider = MagicMock()
        card = _make_feature_card("Add a feature to post daily summaries to Discord")

        final_response = _make_text_response(
            "Spec approved — beginning implementation."
        )

        prior_messages = [
            {"role": "user", "content": "Add a feature to post daily summaries to Discord"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Here is the Feature Spec..."},
            ]},
        ]

        with patch("anthropic.Anthropic") as mock_anthropic:
            client = MagicMock()
            mock_anthropic.return_value = client
            client.messages.create.return_value = final_response

            agent = BaseKanbanAgent(
                profile=open_profile,
                card=card,
                provider=provider,
                api_key="test",
                prior_messages=prior_messages,
                prior_iteration=2,
                resume_user_message="yes, looks good, go ahead",
            )
            result = agent.run()

        assert "implementation" in result.lower() or "approved" in result.lower()


# ── SKILLS-INVENTORY.md ───────────────────────────────────────────────────────

class TestSkillsInventory:
    """The skills inventory doc must list clarify-feature."""

    INVENTORY_MD = REPO_ROOT / "docs" / "info" / "SKILLS-INVENTORY.md"
    pytestmark = pytest.mark.skipif(
        not INVENTORY_MD.exists(),
        reason="docs/info/SKILLS-INVENTORY.md not present (e.g. docs-free CI image)",
    )

    def test_inventory_lists_clarify_feature(self):
        text = self.INVENTORY_MD.read_text(encoding="utf-8")
        assert "clarify-feature" in text, (
            "SKILLS-INVENTORY.md does not list the clarify-feature skill"
        )

    def test_inventory_mentions_clarify_feature_command(self):
        text = self.INVENTORY_MD.read_text(encoding="utf-8")
        # Either /clarify-feature or clarify-feature should appear
        assert "clarify-feature" in text
