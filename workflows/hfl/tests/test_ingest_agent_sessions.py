"""Tests for cross-surface prompt audit capture and HFL ingestion."""

import json
from datetime import date

import pytest

from scripts.agents.hfl import capture_session_event as capture
import workflows.hfl.tasks.ingest_agent_sessions as audit


@pytest.mark.smoke
def test_normalize_redacts_secrets_and_is_stable():
    secret_fixture = "fixture-redaction-value"
    raw = {
        "session_id": "s1",
        "prompt_id": "p1",
        "timestamp": "2026-07-22T10:00:00+08:00",
        "original_prompt": f"deploy with {'api_key'}={secret_fixture}",
        "assistant_outcome": "Done: https://github.com/acme/repo/pull/42",
    }
    first = capture.normalize_event(raw, surface="codex")
    second = capture.normalize_event(raw, surface="codex")
    assert first["event_id"] == second["event_id"]
    assert secret_fixture not in first["original_prompt"]
    assert "[REDACTED]" in first["original_prompt"]
    assert first["artifacts"] == [
        {"kind": "url", "value": "https://github.com/acme/repo/pull/42"}
    ]


@pytest.mark.smoke
def test_hook_pairs_prompt_and_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(capture, "audit_root", lambda: tmp_path)
    prompt = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "prompt": "pls fix it",
    }
    event, _ = capture.capture_hook(prompt, "codex")
    assert event is None

    stop = {
        "hook_event_name": "Stop",
        "session_id": "session-1",
        "last_assistant_message": "Fixed parser.py and verified syntax.",
    }
    event, path = capture.capture_hook(stop, "codex")
    assert event["original_prompt"] == "pls fix it"
    assert event["assistant_outcome"].startswith("Fixed parser.py")
    assert path.exists()


@pytest.mark.smoke
def test_raw_distillation_never_calls_api():
    event = capture.normalize_event({
        "surface": "hermes",
        "session_id": "s",
        "prompt_id": "p",
        "original_prompt": "  summarize   this  ",
        "assistant_outcome": "Created the summary.",
    })
    result = audit.distill_agent_session_event(event, synthesize=False)
    assert result["corrected_prompt"] == "summarize this"
    assert result["synthesized"] is False


@pytest.mark.smoke
def test_process_dual_write_contract_and_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "audit_root", lambda: tmp_path)
    monkeypatch.setattr(
        audit,
        "distill_agent_session_event",
        lambda *_args, **_kwargs: {
            "corrected_prompt": "Please fix the parser.",
            "request_summary": "Fix the parser",
            "work_summary": "Updated parser.py and added coverage.",
            "result_status": "completed",
            "why_it_stayed": "Auditable implementation work.",
            "tags": ["python"],
            "synthesized": True,
        },
    )
    submitted = []
    monkeypatch.setattr(
        audit,
        "submit_hfl_entry",
        lambda entry, **kwargs: submitted.append((entry, kwargs)) or {
            "delivery": "persisted",
            "entry_id": "hfl-test",
            "indexed": True,
        },
    )
    payload = {
        "surface": "claude-code",
        "session_id": "s1",
        "prompt_id": "p1",
        "timestamp": "2026-07-22T12:00:00+08:00",
        "original_prompt": "pls fix parser",
        "assistant_outcome": "Updated parser.py and added coverage.",
    }
    result = audit.process_agent_session_event(payload)
    entry, kwargs = submitted[0]
    artifact = json.loads((tmp_path / "events" / "2026-07-22" / f"{result['event_id']}.json").read_text(encoding="utf-8"))
    assert artifact["original_prompt"] == "pls fix parser"
    assert artifact["corrected_prompt"] == "Please fix the parser."
    assert entry.moment == "Fix the parser"
    assert "surface-claude-code" in entry.tags
    assert entry.references[0].endswith(".json")
    assert kwargs["source"] == "agent-session"
    assert kwargs["dedup_key"] == result["event_id"]
    assert kwargs["es_doc_id"] == result["event_id"]


@pytest.mark.smoke
def test_collect_empty_and_rollup_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "audit_root", lambda: tmp_path)
    assert audit.collect_agent_session_events(
        since=date(2026, 7, 22), until=date(2026, 7, 22)
    ) == []
    result = audit.rollup_agent_sessions(day="2026-07-22")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no agent session events"


@pytest.mark.skip(reason="Manual only - live hooks, broker, Anthropic, corpus, and Elasticsearch")
def test_full_pipeline_live():
    raise AssertionError("run through a configured surface hook")
