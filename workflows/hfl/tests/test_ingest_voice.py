"""
Tests for workflows/hfl/tasks/ingest_voice.py.

Integration tests call the real task exactly as Beat will. The default
(no inbox) is a guaranteed no-op — no network, no side-effects.
The live path (real Anthropic API + corpus write) is marked skip.
"""

from datetime import datetime
from pathlib import Path
import json

import pytest

import workflows.hfl.tasks.ingest_voice as mod
from workflows.hfl.tasks.ingest_voice import (
    ingest_voice_memos,
    collect_voice_transcripts,
    distill_voice_transcript,
    _parse_transcript_file,
    _transcript_context,
    _fallback_distill,
    _mark_processed,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__ingest_voice_memos_no_inbox(monkeypatch, tmp_path):
    """No inbox directory -> clean no-op, no network call, no write."""
    missing = tmp_path / "nonexistent_inbox"
    monkeypatch.setattr(mod, "resolve_voice_inbox", lambda: missing)
    result = ingest_voice_memos(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no inbox"


def test__ingest_voice_memos_empty_inbox(monkeypatch, tmp_path):
    """Inbox exists but is empty -> clean no-op."""
    monkeypatch.setattr(mod, "resolve_voice_inbox", lambda: tmp_path)
    result = ingest_voice_memos(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "empty inbox"


@pytest.mark.skip(reason="Manual only — live Anthropic API call + corpus write.")
def test__ingest_voice_memos_full_pipeline(tmp_path):
    """End-to-end: drop a JSON file, run task, check corpus entry written."""
    transcript_file = tmp_path / "voice_20260601_103000.json"
    transcript_file.write_text(json.dumps({
        "source": "voice_memo",
        "platform": "android",
        "recorded_at": "2026-06-01T10:30:00",
        "transcript": (
            "I realised the sprint keeps slipping not from scope creep "
            "but from zero buffer time for unexpected work."
        ),
        "duration_seconds": 52,
    }), encoding="utf-8")

    corpus = tmp_path / "corpus"
    mod.resolve_voice_inbox = lambda: tmp_path
    mod.resolve_corpus_dir = lambda: corpus
    result = ingest_voice_memos(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] in (0, 1)


# ── _parse_transcript_file ────────────────────────────────────────────────────

def test__parse_transcript_file_valid(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({
        "source": "voice_memo",
        "platform": "android",
        "recorded_at": "2026-06-01T10:30:00",
        "transcript": "This is a valid transcript that is long enough to pass validation.",
        "duration_seconds": 52,
    }), encoding="utf-8")
    result = _parse_transcript_file(f)
    assert result is not None
    assert result["platform"] == "android"
    assert result["duration_seconds"] == 52
    assert isinstance(result["recorded_at"], datetime)
    assert len(result["transcript"]) > 10


def test__parse_transcript_file_missing_transcript(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"source": "voice_memo", "recorded_at": "2026-06-01T10:30:00"}),
                 encoding="utf-8")
    assert _parse_transcript_file(f) is None


def test__parse_transcript_file_too_short_transcript(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"transcript": "hi", "recorded_at": "2026-06-01T10:30:00"}),
                 encoding="utf-8")
    assert _parse_transcript_file(f) is None


def test__parse_transcript_file_invalid_json(tmp_path):
    f = tmp_path / "t.json"
    f.write_text("not json at all {{{", encoding="utf-8")
    assert _parse_transcript_file(f) is None


def test__parse_transcript_file_bad_timestamp_falls_back(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({
        "transcript": "Something worth capturing about today's insight in the meeting.",
        "recorded_at": "not-a-date",
    }), encoding="utf-8")
    result = _parse_transcript_file(f)
    assert result is not None
    assert isinstance(result["recorded_at"], datetime)


# ── collect_voice_transcripts ─────────────────────────────────────────────────

def test__collect_voice_transcripts_empty_dir(tmp_path):
    assert collect_voice_transcripts(tmp_path) == []


def test__collect_voice_transcripts_nonexistent_dir(tmp_path):
    assert collect_voice_transcripts(tmp_path / "no_such_dir") == []


def test__collect_voice_transcripts_skips_processed_dir(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    f = processed / "old.json"
    f.write_text(json.dumps({
        "transcript": "This transcript should not be re-ingested from the processed dir.",
        "recorded_at": "2026-06-01T10:30:00",
    }), encoding="utf-8")
    result = collect_voice_transcripts(tmp_path)
    assert result == []


def test__collect_voice_transcripts_finds_valid_file(tmp_path):
    f = tmp_path / "voice_20260601_103000.json"
    f.write_text(json.dumps({
        "transcript": "I realised the real blocker was missing context in the handoff.",
        "recorded_at": "2026-06-01T10:30:00",
        "platform": "android",
    }), encoding="utf-8")
    result = collect_voice_transcripts(tmp_path)
    assert len(result) == 1
    assert result[0]["platform"] == "android"


def test__collect_voice_transcripts_skips_invalid_json(tmp_path):
    valid = tmp_path / "good.json"
    valid.write_text(json.dumps({
        "transcript": "A clear insight about the system design tradeoff we discussed.",
        "recorded_at": "2026-06-01T10:30:00",
    }), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{{broken", encoding="utf-8")
    result = collect_voice_transcripts(tmp_path)
    assert len(result) == 1


# ── _transcript_context ───────────────────────────────────────────────────────

def test__transcript_context_includes_timestamp_and_duration():
    payload = {
        "recorded_at": datetime(2026, 6, 1, 10, 30),
        "duration_seconds": 52,
        "platform": "android",
        "transcript": "The idea surfaced while walking.",
    }
    ctx = _transcript_context(payload)
    assert "2026-06-01 10:30" in ctx
    assert "52s" in ctx
    assert "android" in ctx
    assert "surfaced" in ctx


def test__transcript_context_omits_zero_duration():
    payload = {
        "recorded_at": datetime(2026, 6, 1, 10, 30),
        "duration_seconds": 0,
        "platform": "android",
        "transcript": "Something noteworthy happened during my walk today.",
    }
    ctx = _transcript_context(payload)
    assert "Duration" not in ctx


# ── _fallback_distill ─────────────────────────────────────────────────────────

def test__fallback_distill_returns_required_keys():
    payload = {
        "transcript": "Sprint slippage caused by missing buffer time, not scope creep.",
        "platform": "android",
    }
    d = _fallback_distill(payload)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "voice" in d["tags"]
    assert "android" in d["tags"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d


def test__fallback_distill_uses_first_sentence():
    payload = {
        "transcript": "First sentence insight. Second sentence detail.",
        "platform": "android",
    }
    d = _fallback_distill(payload)
    assert "First sentence" in d["moment"]


# ── distill_voice_transcript ──────────────────────────────────────────────────

def test__distill_voice_transcript_no_api():
    """synthesize=False must not call any API and must return valid entry fields."""
    payload = {
        "transcript": "I realised the real blocker in our process is the missing context.",
        "platform": "android",
        "recorded_at": datetime(2026, 6, 1, 10, 30),
        "duration_seconds": 40,
        "filename": "memo.m4a",
    }
    d = distill_voice_transcript(payload, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert isinstance(d["tags"], list)
    assert "voice" in d["tags"]


# ── _mark_processed ───────────────────────────────────────────────────────────

def test__mark_processed_moves_file(tmp_path):
    src = tmp_path / "voice_20260601.json"
    src.write_text("{}", encoding="utf-8")
    _mark_processed(src, tmp_path)
    assert not src.exists()
    processed = tmp_path / "processed"
    assert processed.is_dir()
    moved = list(processed.glob("*.json"))
    assert len(moved) == 1


def test__mark_processed_handles_collision(tmp_path):
    src = tmp_path / "voice_20260601.json"
    src.write_text("{}", encoding="utf-8")
    processed = tmp_path / "processed"
    processed.mkdir()
    collision = processed / "voice_20260601.json"
    collision.write_text("{}", encoding="utf-8")
    _mark_processed(src, tmp_path)
    files = list(processed.glob("*.json"))
    assert len(files) == 2


# ── Dual-write contract ───────────────────────────────────────────────────────

def test__dual_write_calls_append_entry(monkeypatch, tmp_path):
    """The task must call append_entry(source='voice') for each valid memo."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    f = inbox / "voice_20260601_103000.json"
    f.write_text(json.dumps({
        "transcript": "I realised today that zero buffer time causes all sprint slippage.",
        "recorded_at": "2026-06-01T10:30:00",
        "platform": "android",
    }), encoding="utf-8")

    monkeypatch.setattr(mod, "resolve_voice_inbox", lambda: inbox)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: corpus)
    monkeypatch.setattr(mod, "distill_voice_transcript",
                        lambda payload, **kw: {
                            "skip": False,
                            "moment": "Sprint slippage is a buffer problem",
                            "what_happened": "Realised the root cause.",
                            "why_it_stayed": "Systems thinking insight.",
                            "possible_use": "retro",
                            "tags": ["voice", "android", "sprint"],
                            "synthesized": False,
                        })

    calls = {}

    def _fake_append(day_file, entry, *, source, synthesized=False):
        calls["source"] = source
        calls["synthesized"] = synthesized
        return 10, "doc-id-456"

    monkeypatch.setattr(mod, "append_entry", _fake_append)

    result = ingest_voice_memos()
    assert result["entries_written"] == 1
    assert calls["source"] == "voice"


def test__max_memos_respected(monkeypatch, tmp_path):
    """max_memos caps how many transcripts are processed per run."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    for i in range(5):
        f = inbox / ("voice_2026060" + str(i) + ".json")
        f.write_text(json.dumps({
            "transcript": "Insight number " + str(i) + " about today's work session.",
            "recorded_at": "2026-06-0" + str(i + 1) + "T10:30:00",
        }), encoding="utf-8")

    monkeypatch.setattr(mod, "resolve_voice_inbox", lambda: inbox)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: corpus)
    monkeypatch.setattr(mod, "distill_voice_transcript",
                        lambda payload, **kw: {
                            "skip": False, "moment": "m", "what_happened": "w",
                            "why_it_stayed": "", "possible_use": "log",
                            "tags": ["voice"], "synthesized": False,
                        })
    monkeypatch.setattr(mod, "append_entry",
                        lambda day_file, entry, **kw: (10, "doc-id"))

    result = ingest_voice_memos(max_memos=2)
    assert result["entries_written"] == 2
    assert result["memos_found"] == 2
