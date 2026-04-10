"""
Tests for the agents/kanban/security/ layer.

All tests are fully offline — no API calls, no filesystem side effects
(tmp_path fixtures used where file output is needed).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agents.kanban.security.audit import AuditLogger, NullAuditLogger
from agents.kanban.security.sanitizer import OutputSanitizer
from agents.kanban.security.secret_store import SecretStore


# ─────────────────────────────────────────────────────────────────────────────
# SecretStore
# ─────────────────────────────────────────────────────────────────────────────

class TestSecretStore:
    def _store(self, extra: dict | None = None):
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-123456789012345678901234",
            "TRELLO_API_KEY": "trello_key_abc",
            "TRELLO_API_TOKEN": "trello_token_xyz",
            "YNAB_PERSONAL_ACCESS_TOKEN": "ynab_token_secret",
            "UNRELATED_VAR": "should_never_appear",
        }
        if extra:
            env.update(extra)
        return SecretStore(env=env)

    def test_scoped_returns_only_requested(self):
        store = self._store()
        result = store.scoped(["ANTHROPIC_API_KEY", "TRELLO_API_KEY"])
        assert set(result.keys()) == {"ANTHROPIC_API_KEY", "TRELLO_API_KEY"}
        assert "UNRELATED_VAR" not in result
        assert "YNAB_PERSONAL_ACCESS_TOKEN" not in result

    def test_scoped_raises_on_missing(self):
        store = self._store()
        with pytest.raises(KeyError, match="MISSING_VAR"):
            store.scoped(["ANTHROPIC_API_KEY", "MISSING_VAR"])

    def test_scoped_empty_list_returns_empty(self):
        store = self._store()
        result = store.scoped([])
        assert result == {}

    def test_scoped_for_profile_reads_secrets_section(self):
        from agents.kanban.profiles.schema import AgentProfile, SecretsConfig
        store = self._store()
        profile = AgentProfile(
            id="test",
            name="Test",
            secrets=SecretsConfig(required=["ANTHROPIC_API_KEY", "TRELLO_API_KEY"]),
        )
        result = store.scoped_for_profile(profile)
        assert "ANTHROPIC_API_KEY" in result
        assert "TRELLO_API_KEY" in result
        assert "UNRELATED_VAR" not in result

    def test_pack_unpack_plain(self):
        store = self._store()
        payload = store.pack({"KEY": "value"})
        assert payload.startswith("plain:")
        recovered = store.unpack(payload)
        assert recovered == {"KEY": "value"}

    def test_scoped_for_profile_no_secrets_section(self):
        """Profiles without a secrets: block return an empty scoped dict."""
        from agents.kanban.profiles.schema import AgentProfile
        store = self._store()
        profile = AgentProfile(id="bare", name="Bare")
        result = store.scoped_for_profile(profile)
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# OutputSanitizer
# ─────────────────────────────────────────────────────────────────────────────

class TestOutputSanitizer:
    def _sanitizer(self):
        return OutputSanitizer({
            "ANTHROPIC_API_KEY": "sk-ant-verysecretkey123456",
            "TRELLO_TOKEN": "trello_token_abcdef1234567890",
            "SHORT": "hi",   # too short — should not be redacted
        })

    def test_scrub_replaces_exact_secret(self):
        s = self._sanitizer()
        result = s.scrub("Here is your key: sk-ant-verysecretkey123456 — enjoy")
        assert "sk-ant-verysecretkey123456" not in result
        assert "[REDACTED]" in result

    def test_scrub_replaces_all_occurrences(self):
        s = self._sanitizer()
        text = "key1=sk-ant-verysecretkey123456 key2=sk-ant-verysecretkey123456"
        result = s.scrub(text)
        assert result.count("[REDACTED]") == 2

    def test_scrub_does_not_redact_short_values(self):
        s = self._sanitizer()
        result = s.scrub("hi there, this is fine")
        assert "hi" in result
        assert "[REDACTED]" not in result

    def test_scrub_clean_text_unchanged(self):
        s = self._sanitizer()
        text = "All tests passed successfully."
        assert s.scrub(text) == text

    def test_scrub_messages_dict_content(self):
        s = self._sanitizer()
        messages = [
            {"role": "assistant", "content": "token=trello_token_abcdef1234567890"},
            {"role": "user", "content": "normal message"},
        ]
        s.scrub_messages(messages)
        assert "trello_token_abcdef1234567890" not in messages[0]["content"]
        assert "[REDACTED]" in messages[0]["content"]
        assert messages[1]["content"] == "normal message"

    def test_scrub_messages_list_content(self):
        s = self._sanitizer()
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "key=sk-ant-verysecretkey123456"},
                    {"type": "tool_result", "content": "trello_token_abcdef1234567890"},
                ],
            }
        ]
        s.scrub_messages(messages)
        blocks = messages[0]["content"]
        assert "[REDACTED]" in blocks[0]["text"]
        assert "[REDACTED]" in blocks[1]["content"]

    def test_no_secrets_sanitizer_is_passthrough(self):
        s = OutputSanitizer({})
        text = "This has no secrets to scrub"
        assert s.scrub(text) == text


# ─────────────────────────────────────────────────────────────────────────────
# AuditLogger
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditLogger:
    def test_writes_jsonl_records(self, tmp_path):
        log_file = tmp_path / "audit.jsonl"
        audit = AuditLogger("agent:test", "card123", log_path=log_file)

        audit.agent_start("My card title")
        audit.tool_call("read_file", {"path": "/tmp/foo.py"})
        audit.tool_result("read_file", success=True, detail="ok")
        audit.permission_check("filesystem", "/tmp/foo.py", allowed=True)
        audit.secret_access("agent:test", ["ANTHROPIC_API_KEY"])
        audit.agent_finish(success=True, iterations=3)

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 6

        events = [json.loads(l) for l in lines]
        event_types = [e["event"] for e in events]
        assert event_types == [
            "agent_start", "tool_call", "tool_result",
            "permission_check", "secret_access", "agent_finish",
        ]

    def test_all_records_have_required_fields(self, tmp_path):
        log_file = tmp_path / "audit.jsonl"
        audit = AuditLogger("agent:test", "card123", log_path=log_file)
        audit.card_lifecycle("Backlog", "Pending")

        record = json.loads(log_file.read_text())
        assert "ts" in record
        assert record["agent_id"] == "agent:test"
        assert record["card_id"] == "card123"
        assert record["event"] == "card_lifecycle"

    def test_creates_parent_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "audit.jsonl"
        audit = AuditLogger("agent:test", "card123", log_path=nested)
        audit.agent_start("title")
        assert nested.exists()

    def test_null_audit_logger_writes_nothing(self, tmp_path):
        audit = NullAuditLogger()
        # Should not raise even though no path is configured
        audit.agent_start("title")
        audit.tool_call("bash", {"cmd": "ls"})
        audit.agent_finish(success=True, iterations=1)

    def test_tool_call_omits_secret_looking_inputs(self, tmp_path):
        """Audit records should not contain raw secret-looking values."""
        log_file = tmp_path / "audit.jsonl"
        audit = AuditLogger("agent:test", "card123", log_path=log_file)
        # A long base64-ish value should be omitted from the audit record
        audit.tool_call("some_tool", {"api_key": "A" * 40, "label": "hello"})

        record = json.loads(log_file.read_text())
        assert record["inputs"]["api_key"] == "<omitted>"
        assert record["inputs"]["label"] == "hello"


# ─────────────────────────────────────────────────────────────────────────────
# Schema — SecretsConfig in AgentProfile
# ─────────────────────────────────────────────────────────────────────────────

class TestSecretsSchema:
    def test_from_dict_parses_secrets(self):
        from agents.kanban.profiles.schema import AgentProfile
        data = {
            "id": "agent:test",
            "name": "Test",
            "secrets": {
                "required": ["ANTHROPIC_API_KEY", "TRELLO_API_KEY"],
            },
        }
        profile = AgentProfile.from_dict(data)
        assert profile.secrets.required == ["ANTHROPIC_API_KEY", "TRELLO_API_KEY"]

    def test_from_dict_no_secrets_section_defaults_to_empty(self):
        from agents.kanban.profiles.schema import AgentProfile
        data = {"id": "agent:test", "name": "Test"}
        profile = AgentProfile.from_dict(data)
        assert profile.secrets.required == []

    def test_merge_base_unions_required_secrets(self):
        from agents.kanban.profiles.schema import AgentProfile, SecretsConfig
        base = AgentProfile(
            id="base",
            name="Base",
            secrets=SecretsConfig(required=["ANTHROPIC_API_KEY", "TRELLO_API_KEY"]),
        )
        child = AgentProfile(
            id="child",
            name="Child",
            secrets=SecretsConfig(required=["YNAB_PERSONAL_ACCESS_TOKEN"]),
        )
        merged = child.merge_base(base)
        # child's secrets + base's secrets, deduplicated, child-first
        assert "YNAB_PERSONAL_ACCESS_TOKEN" in merged.secrets.required
        assert "ANTHROPIC_API_KEY" in merged.secrets.required
        assert "TRELLO_API_KEY" in merged.secrets.required
        # No duplicates
        assert len(merged.secrets.required) == len(set(merged.secrets.required))

    def test_example_profiles_have_secrets_section(self):
        from agents.kanban.profiles.schema import AgentProfile
        examples = Path(__file__).parent.parent / "profiles" / "examples"
        for yaml_file in examples.glob("*.yaml"):
            if yaml_file.name == "base.yaml":
                continue  # base doesn't need all secrets
            profile = AgentProfile.from_yaml(yaml_file)
            assert len(profile.secrets.required) > 0, (
                f"{yaml_file.name} has no secrets.required declared"
            )
