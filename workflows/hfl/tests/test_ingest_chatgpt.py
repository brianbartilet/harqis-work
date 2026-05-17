"""
Tests for workflows/hfl/tasks/ingest_chatgpt.py.

Integration tests call the real task exactly as Beat will. The default
(no CHATGPT_WEB_ACCESS_TOKEN) is a guaranteed no-op — no network, no
side-effects. The live path (real ChatGPT web backend round-trip + corpus
write) is marked skip.
"""

import pytest

from workflows.hfl.tasks.ingest_chatgpt import (
    ingest_chatgpt_activity,
    distill_chatgpt_activity,
    _extract_user_messages,
    _coerce_dt,
    _activity_body,
)
from datetime import date, datetime


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__ingest_chatgpt_activity_no_token(monkeypatch):
    """No token configured → clean no-op, no network call, no corpus write."""
    monkeypatch.delenv("CHATGPT_WEB_ACCESS_TOKEN", raising=False)
    result = ingest_chatgpt_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no token"


@pytest.mark.skip(reason="Manual only — live UNOFFICIAL ChatGPT web backend "
                         "round-trip (needs a valid CHATGPT_WEB_ACCESS_TOKEN) "
                         "+ Anthropic; appends a real entry to today's corpus.")
def test__ingest_chatgpt_activity_full_pipeline():
    result = ingest_chatgpt_activity(cfg_id__anthropic="ANTHROPIC", window_days=7)
    assert result["entries_written"] in (0, 1)


# ── Unit / function ───────────────────────────────────────────────────────────

def test__coerce_dt_epoch_float():
    dt = _coerce_dt(1_700_000_000.0)
    assert isinstance(dt, datetime)


def test__coerce_dt_iso_string_and_garbage():
    assert _coerce_dt("2026-05-17T09:00:00.000000+00:00").date() == date(2026, 5, 17)
    assert _coerce_dt("not-a-date") is None
    assert _coerce_dt(None) is None


def test__extract_user_messages_filters_role_and_window():
    ts = datetime(2026, 5, 17, 9, 0).timestamp()
    detail = {
        "mapping": {
            "n1": {"message": {
                "author": {"role": "user"},
                "create_time": ts,
                "content": {"content_type": "text", "parts": ["how do celery beats dedupe"]},
            }},
            "n2": {"message": {
                "author": {"role": "assistant"},
                "create_time": ts,
                "content": {"content_type": "text", "parts": ["they don't, beat is singular"]},
            }},
            "n3": {"message": {
                "author": {"role": "user"},
                "create_time": datetime(2020, 1, 1).timestamp(),
                "content": {"content_type": "text", "parts": ["old, out of window"]},
            }},
        }
    }
    msgs = _extract_user_messages(detail, since=date(2026, 5, 16), until=date(2026, 5, 17))
    assert len(msgs) == 1
    assert "celery beats dedupe" in msgs[0]["text"]
    assert msgs[0]["when"].startswith("2026-05-17")


def test__extract_user_messages_empty_mapping():
    assert _extract_user_messages({}, since=date(2026, 5, 1), until=date(2026, 5, 2)) == []


def test__activity_body_structure():
    activity = {
        "conversations": [
            {"id": "c1", "title": "Celery on Windows", "messages": [
                {"when": "2026-05-17 09:00", "text": "gevent vs threads"},
            ]},
        ],
        "message_count": 1,
        "conversation_count": 1,
    }
    body = _activity_body(activity)
    assert "Celery on Windows" in body
    assert "gevent vs threads" in body


def test__distill_chatgpt_activity_raw_fallback_no_api():
    """synthesize=False must not call any API and must return entry fields."""
    activity = {
        "conversations": [
            {"id": "c1", "title": "HFL method", "messages": [
                {"when": "2026-05-17 09:00", "text": "homework for life structure"},
            ]},
        ],
        "message_count": 1,
        "conversation_count": 1,
    }
    d = distill_chatgpt_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "1 ChatGPT prompt" in d["moment"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d
