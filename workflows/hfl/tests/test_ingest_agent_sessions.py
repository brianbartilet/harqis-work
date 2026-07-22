"""Tests for cross-surface prompt audit capture and HFL ingestion."""

import json
import re
from datetime import date
from pathlib import Path

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
def test_raw_distillation_keeps_moment_brief_and_formats_sections():
    event = capture.normalize_event({
        "surface": "hermes",
        "session_id": "s",
        "prompt_id": "p",
        "original_prompt": (
            "Can you improve the prompt audit migration readability, keep Moment brief, "
            "merge compacted-session residue, and rerun the last 90 days?"
        ),
        "assistant_outcome": (
            "Updated the migration. Added regression tests. Reran the backfill and verified parity."
        ),
    })

    distilled = audit.distill_agent_session_event(event, synthesize=False)
    rendered = audit.format_agent_session_happened(distilled)

    assert len(distilled["request_summary"]) <= 120
    assert distilled["request_summary"] == "Improve the prompt-audit migration and rerun the last 90 days"
    assert rendered.startswith("### Request\n")
    assert "\n\n### Outcome\n" in rendered
    assert "- Updated the migration." in rendered
    assert "- Added regression tests." in rendered
    assert not re.search(r"^#{1,2}\s", rendered, re.MULTILINE)


def test_what_happened_preserves_safe_markdown_without_h2_headings():
    rendered = audit.format_agent_session_happened({
        "request_summary": "Deploy the **HARQIS** stack",
        "work_summary": (
            "## Result\n"
            "- Branch: `main`\n"
            "- [Frontend](https://example.test): **healthy**\n"
            "| Service | Status |\n|---|---|\n| Redis | healthy |\n"
            "```bash\ncurl /health\n```"
        ),
    })

    assert rendered == (
        "### Request\n"
        "Deploy the **HARQIS** stack\n\n"
        "### Outcome\n"
        "#### Result\n"
        "- Branch: `main`\n"
        "- [Frontend](https://example.test): **healthy**\n"
        "| Service | Status |\n"
        "|---|---|\n"
        "| Redis | healthy |\n"
        "```bash\n"
        "curl /health\n"
        "```"
    )
    assert not re.search(r"^#{1,2}\s", rendered, re.MULTILINE)


@pytest.mark.smoke
def test_raw_distillation_summarizes_fragment_answers_from_visible_outcome():
    event = capture.normalize_event({
        "surface": "hermes",
        "session_id": "s",
        "prompt_id": "p",
        "original_prompt": "1. Claude Code locally 2. weekly Friday 3. continuous 4. draft PR",
        "assistant_outcome": (
            "Got it. Weekly Friday scanning with a draft PR ready for review.\n"
            "- Checked the local setup\n"
            "- Prepared the schedule"
        ),
    })

    distilled = audit.distill_agent_session_event(event, synthesize=False)

    assert distilled["request_summary"] == (
        "Weekly Friday scanning with a draft PR ready for review"
    )
    assert "\n- Checked the local setup\n- Prepared the schedule" in distilled["work_summary"]


def test_raw_distillation_summarizes_long_structured_outcomes_without_cutting_lines():
    event = capture.normalize_event({
        "surface": "hermes",
        "session_id": "s",
        "prompt_id": "p",
        "original_prompt": "Analyze why context grows quickly",
        "assistant_outcome": (
            "The model is not the main problem. The fixed tool payload is.\n\n"
            "Current baseline per request:\n"
            "| Component | Tokens |\n|---|---:|\n| **Total before conversation** | **83,864** |\n"
            "So only around **52,000 tokens** remain before compression.\n\n"
            "Main causes, ranked:\n\n"
            "1. **Every MCP tool is exposed**\n"
            "- 385 tools consume about 61K tokens.\n"
            "- This is the dominant cause.\n\n"
            "2. **Schemas are resent on every call**\n"
            "- Prompt caching helps cost, not context occupancy.\n\n"
            "3. **Tool-heavy turns keep growing history**\n"
            "- Terminal and browser results remain visible.\n\n"
            + "Additional low-value detail. " * 80
            + "\n`protect_last_n"
        ),
    })

    distilled = audit.distill_agent_session_event(event, synthesize=False)

    assert len(distilled["work_summary"]) <= 900
    assert distilled["work_summary"].startswith(
        "The model is not the main problem. The fixed tool payload is."
    )
    assert "- **Every MCP tool is exposed:** This is the dominant cause." in distilled["work_summary"]
    assert "- **Total before conversation:** 83,864" in distilled["work_summary"]
    assert "- **Schemas are resent on every call:** Prompt caching helps cost" in distilled["work_summary"]
    assert "protect_last_n" not in distilled["work_summary"]


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
    assert entry.what_happened == (
        "### Request\nFix the parser\n\n"
        "### Outcome\n- Updated parser.py and added coverage."
    )
    assert "surface-claude-code" in entry.tags
    assert entry.references == (entry.references[0],)
    assert entry.references[0].endswith(".json")
    assert kwargs["source"] == "agent-session"
    assert kwargs["dedup_key"] == result["event_id"]
    assert kwargs["es_doc_id"] == result["event_id"]


def test_process_keeps_commit_artifacts_in_audit_but_not_hfl_references(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(audit, "audit_root", lambda: tmp_path)
    submitted = []
    monkeypatch.setattr(
        audit,
        "submit_hfl_entry",
        lambda entry, **kwargs: submitted.append((entry, kwargs)) or {
            "entry_id": "hfl-test",
            "path": str(tmp_path / "2026-07-21.md"),
            "bytes_written": 1,
            "duplicate": False,
            "indexed": True,
        },
    )
    payload = {
        "surface": "hermes",
        "session_id": "session",
        "prompt_id": "prompt",
        "timestamp": "2026-07-21T20:09:04+08:00",
        "original_prompt": "Pull latest and restart",
        "assistant_outcome": "Updated b8cf522 to b09033a and restarted.",
        "artifacts": [
            {"kind": "commit", "value": "b8cf522"},
            {"kind": "commit", "value": "b09033a"},
        ],
    }

    result = audit.process_agent_session_event(payload, synthesize=False)
    artifact = json.loads(Path(result["artifact"]).read_text(encoding="utf-8"))

    assert artifact["artifacts"] == payload["artifacts"]
    assert submitted[0][0].references == (result["artifact"],)


@pytest.mark.smoke
def test_collect_empty_and_rollup_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "audit_root", lambda: tmp_path)
    assert audit.collect_agent_session_events(
        since=date(2026, 7, 22), until=date(2026, 7, 22)
    ) == []
    result = audit.rollup_agent_sessions(day="2026-07-22")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no agent session events"


def test_collect_ignores_appledouble_and_non_utf8_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "audit_root", lambda: tmp_path)
    day_dir = tmp_path / "events" / "2026-07-22"
    day_dir.mkdir(parents=True)
    (day_dir / "._agent-one.json").write_bytes(b"\x00\x05\x16\x07\x00\xb0")
    (day_dir / "broken.json").write_bytes(b"\xff\xfe")
    valid = {
        "event_id": "agent-one",
        "timestamp": "2026-07-22T10:00:00+08:00",
        "ingest": {"delivery": "persisted"},
    }
    (day_dir / "agent-one.json").write_text(json.dumps(valid), encoding="utf-8")

    events = audit.collect_agent_session_events(
        since=date(2026, 7, 22), until=date(2026, 7, 22), processed_only=True
    )

    assert [event["event_id"] for event in events] == ["agent-one"]


@pytest.mark.skip(reason="Manual only - live hooks, broker, Anthropic, corpus, and Elasticsearch")
def test_full_pipeline_live():
    raise AssertionError("run through a configured surface hook")
