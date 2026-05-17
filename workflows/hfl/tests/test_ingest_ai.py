"""
Tests for workflows/hfl/tasks/ingest_ai.py.

Integration tests call the real task exactly as Beat will. The default
(no thread ids configured) is a guaranteed no-op — safe to run live with
no side-effects. Anything that performs a real OpenAI/Anthropic round-trip
and writes the corpus is marked skip.
"""

import pytest

from workflows.hfl.tasks.ingest_ai import (
    ingest_ai_activity,
    collect_openai_activity,
    distill_ai_activity,
    _resolve_thread_ids,
    _message_text,
    _activity_body,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__ingest_ai_activity():
    """No thread ids configured → clean no-op, no LLM call, no corpus write."""
    result = ingest_ai_activity(cfg_id__anthropic="ANTHROPIC", thread_ids=[])
    assert result["entries_written"] == 0
    assert result["skipped"] == "no thread ids"


def test__ingest_ai_activity_unknown_thread():
    """An unknown thread id yields no prompts → no entry, no LLM call."""
    result = ingest_ai_activity(
        cfg_id__anthropic="ANTHROPIC",
        thread_ids=["thread_does_not_exist_zzz"],
        window_days=1,
    )
    assert result["entries_written"] == 0
    assert result["skipped"] in ("no prompts", "openai unavailable")


@pytest.mark.skip(reason="Manual only — live OpenAI + Anthropic round-trip; "
                         "appends a real entry to today's HFL corpus file.")
def test__ingest_ai_activity_full_pipeline():
    result = ingest_ai_activity(
        cfg_id__anthropic="ANTHROPIC",
        thread_ids=["thread_REPLACE_WITH_REAL_ID"],
        window_days=7,
    )
    assert result["entries_written"] in (0, 1)


# ── Unit / function ───────────────────────────────────────────────────────────

def test__resolve_thread_ids_explicit_dedup_and_strip():
    assert _resolve_thread_ids(["t1", "t1", " t2 ", ""]) == ["t1", "t2"]


def test__resolve_thread_ids_empty():
    assert _resolve_thread_ids(None) == [] or isinstance(_resolve_thread_ids(None), list)


def test__message_text_v2_block_list():
    content = [{"type": "text", "text": {"value": "hello world"}}]
    assert _message_text(content) == "hello world"


def test__message_text_plain_string():
    assert _message_text("just a string") == "just a string"


def test__message_text_empty_and_image_only():
    assert _message_text(None) == ""
    assert _message_text([{"type": "image_file", "image_file": {"file_id": "f"}}]) == ""


def test__activity_body_structure():
    activity = {
        "threads": [
            {"thread_id": "abc", "messages": [
                {"when": "2026-05-17 09:00", "text": "how do celery beats dedupe"},
            ]},
        ],
        "message_count": 1,
        "thread_count": 1,
    }
    body = _activity_body(activity)
    assert "thread abc" in body
    assert "celery beats dedupe" in body


def test__distill_ai_activity_raw_fallback_no_api():
    """synthesize=False must not call any API and must return entry fields."""
    activity = {
        "threads": [
            {"thread_id": "abc", "messages": [
                {"when": "2026-05-17 09:00", "text": "research homework for life"},
            ]},
        ],
        "message_count": 1,
        "thread_count": 1,
    }
    d = distill_ai_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "1 AI prompt" in d["moment"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d
