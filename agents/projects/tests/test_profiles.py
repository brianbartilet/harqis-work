"""
Tests for profile schema loading and the profile registry.
"""

import textwrap
from pathlib import Path

import pytest
import yaml
from hamcrest import assert_that, equal_to, contains_string, instance_of, has_length, none

from agents.projects.trello.models import KanbanCard
from agents.projects.profiles.registry import ProfileRegistry
from agents.projects.profiles.schema import AgentProfile, ModelConfig, ToolsConfig


@pytest.mark.smoke
def test_profile_from_dict_minimal():
    data = {"id": "agent:test", "name": "Test Agent"}
    profile = AgentProfile.from_dict(data)

    assert_that(profile.id, equal_to("agent:test"))
    assert_that(profile.name, equal_to("Test Agent"))
    assert_that(profile.model, instance_of(ModelConfig))
    assert_that(profile.model.model_id, equal_to("claude-sonnet-4-6"))


@pytest.mark.smoke
def test_profile_from_dict_full():
    data = {
        "id": "agent:code:harqis",
        "name": "Code Agent",
        "model": {
            "provider": "anthropic",
            "model_id": "claude-opus-4-6",
            "max_tokens": 8192,
        },
        "tools": {
            "allowed": ["bash", "read_file"],
            "denied": ["web_search"],
        },
        "permissions": {
            "filesystem": {"allow": ["/workspace/**"], "deny": ["/secrets/**"]},
            "network": {"allow": ["api.github.com"], "deny": ["*"]},
            "git": {"can_push": True, "protected_branches": ["main"]},
        },
        "lifecycle": {"timeout_minutes": 30, "auto_approve": False},
    }
    profile = AgentProfile.from_dict(data)

    assert_that(profile.model.model_id, equal_to("claude-opus-4-6"))
    assert_that(profile.model.max_tokens, equal_to(8192))
    assert_that(profile.tools.allowed, equal_to(["bash", "read_file"]))
    assert_that(profile.tools.denied, equal_to(["web_search"]))
    assert_that(profile.permissions.git.can_push, equal_to(True))
    assert_that(profile.lifecycle.timeout_minutes, equal_to(30))


@pytest.mark.smoke
def test_profile_from_yaml(tmp_path):
    yaml_content = textwrap.dedent("""
        id: agent:write
        name: Write Agent
        model:
          model_id: claude-haiku-4-5-20251001
          max_tokens: 2048
        tools:
          allowed:
            - read_file
            - write_file
        lifecycle:
          auto_approve: true
    """)
    p = tmp_path / "agent_write.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    profile = AgentProfile.from_yaml(p)

    assert_that(profile.id, equal_to("agent:write"))
    assert_that(profile.model.model_id, equal_to("claude-haiku-4-5-20251001"))
    assert_that(profile.lifecycle.auto_approve, equal_to(True))


@pytest.mark.smoke
def test_profile_matches_label():
    profile = AgentProfile(id="agent:code", name="Code")
    assert_that(profile.matches_label("agent:code"), equal_to(True))
    assert_that(profile.matches_label("agent:write"), equal_to(False))


@pytest.mark.smoke
def test_registry_load_dir(tmp_path):
    yaml_a = tmp_path / "a.yaml"
    yaml_a.write_text("id: agent:a\nname: Agent A\n", encoding="utf-8")
    yaml_b = tmp_path / "b.yaml"
    yaml_b.write_text("id: agent:b\nname: Agent B\n", encoding="utf-8")

    registry = ProfileRegistry.from_dir(tmp_path)

    assert_that(len(registry), equal_to(2))
    assert_that("agent:a" in registry, equal_to(True))
    assert_that("agent:b" in registry, equal_to(True))


@pytest.mark.smoke
def test_registry_resolve_exact_label(tmp_path, sample_card):
    yaml_code = tmp_path / "code.yaml"
    yaml_code.write_text("id: agent:code\nname: Code Agent\n", encoding="utf-8")

    registry = ProfileRegistry.from_dir(tmp_path)
    profile = registry.resolve_for_card(sample_card)  # card has label "agent:code"

    assert_that(profile, instance_of(AgentProfile))
    assert_that(profile.id, equal_to("agent:code"))


@pytest.mark.smoke
def test_registry_resolve_no_match(tmp_path, minimal_card):
    yaml_other = tmp_path / "other.yaml"
    yaml_other.write_text("id: agent:data\nname: Data Agent\n", encoding="utf-8")

    registry = ProfileRegistry.from_dir(tmp_path)
    # minimal_card has label "agent:write", not "agent:data"
    profile = registry.resolve_for_card(minimal_card)

    assert_that(profile, none())


@pytest.mark.smoke
def test_registry_profile_inheritance(tmp_path):
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(textwrap.dedent("""
        id: base
        name: Base
        model:
          model_id: claude-haiku-4-5-20251001
          max_tokens: 1024
        lifecycle:
          timeout_minutes: 10
          auto_approve: false
    """), encoding="utf-8")

    child_yaml = tmp_path / "child.yaml"
    child_yaml.write_text(textwrap.dedent("""
        id: agent:child
        name: Child Agent
        extends: base
        lifecycle:
          auto_approve: true
    """), encoding="utf-8")

    registry = ProfileRegistry.from_dir(tmp_path)
    child = registry.resolve("agent:child")

    assert_that(child, instance_of(AgentProfile))
    # inherits model from base
    assert_that(child.model.model_id, equal_to("claude-haiku-4-5-20251001"))
    # overrides lifecycle
    assert_that(child.lifecycle.auto_approve, equal_to(True))


@pytest.mark.smoke
def test_load_example_profiles():
    """All bundled example profiles must load without errors."""
    examples = Path(__file__).parent.parent / "profiles" / "examples"
    registry = ProfileRegistry.from_dir(examples)
    assert_that(len(registry) > 0, equal_to(True))
