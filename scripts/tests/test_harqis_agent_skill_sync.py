"""Tests for HARQIS agent-skill mirroring into Hermes."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import yaml


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "agents"
    / "repo-quality"
    / "harqis_agent_skill_sync.py"
)
SPEC = importlib.util.spec_from_file_location("harqis_agent_skill_sync", SCRIPT)
assert SPEC and SPEC.loader
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


def test_sync_quick_commands_adds_and_repairs_aliases_without_touching_other_config(
    tmp_path: Path,
):
    config = tmp_path / "config.yaml"
    config.write_text(
        "# retained comment\n"
        "model:\n"
        "  default: test-model\n"
        "quick_commands:\n"
        "  existing:\n"
        "    type: alias\n"
        "    target: harqis-existing\n"
        "  wrong:\n"
        "    type: alias\n"
        "    target: stale-target\n"
        "display:\n"
        "  skin: default\n",
        encoding="utf-8",
    )

    result = sync.sync_quick_commands(
        config,
        {
            "existing": "harqis-existing",
            "new-skill": "harqis-new-skill",
            "wrong": "harqis-wrong",
        },
    )

    parsed = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert parsed["quick_commands"]["existing"] == {
        "type": "alias",
        "target": "harqis-existing",
    }
    assert parsed["quick_commands"]["new-skill"] == {
        "type": "alias",
        "target": "harqis-new-skill",
    }
    assert parsed["quick_commands"]["wrong"] == {
        "type": "alias",
        "target": "harqis-wrong",
    }
    assert parsed["model"] == {"default": "test-model"}
    assert parsed["display"] == {"skin": "default"}
    assert config.read_text(encoding="utf-8").startswith("# retained comment\n")
    assert result == {
        "created": ["new-skill"],
        "updated": ["wrong"],
        "unchanged": ["existing"],
    }


def test_sync_quick_commands_check_only_reports_drift_without_writing(tmp_path: Path):
    config = tmp_path / "config.yaml"
    original = "quick_commands: {}\n"
    config.write_text(original, encoding="utf-8")

    result = sync.sync_quick_commands(
        config,
        {"new-skill": "harqis-new-skill"},
        check_only=True,
    )

    assert result == {"created": ["new-skill"], "updated": [], "unchanged": []}
    assert config.read_text(encoding="utf-8") == original


def test_full_check_does_not_create_hermes_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    source = repo / ".agents" / "skills" / "sample" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\n"
        "name: sample\n"
        "description: Sample skill.\n"
        "---\n\n"
        "# Sample\n",
        encoding="utf-8",
    )
    hermes_home = tmp_path / "hermes"

    result, has_delta = sync.sync(
        sync._paths(repo, hermes_home),
        check_only=True,
    )

    assert has_delta is True
    assert result["created"] == ["harqis-sample"]
    assert result["aliases"]["created"] == ["sample"]
    assert not hermes_home.exists()
