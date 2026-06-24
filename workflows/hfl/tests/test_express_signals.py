"""Tests for the HFL auto-express signal hook (Option B / Phase 1).

The hook turns a successful task run into a buffered signal IFF the task's
manifesto declares ``hfl_express: 'buffer'``. These tests exercise the pure
logic (summarize + opt-in gate) with the ES buffer write monkeypatched, so no
Elasticsearch and no Celery is needed.
"""
import pytest
from hamcrest import assert_that, equal_to, is_, none, not_none

from workflows.hfl import express_signals


@pytest.fixture()
def captured(monkeypatch):
    """Capture index_hfl_signal calls instead of writing to ES."""
    calls: list[dict] = []

    def _fake_index(**kwargs):
        calls.append(kwargs)
        return "doc-1"

    monkeypatch.setattr(express_signals, "index_hfl_signal", _fake_index)
    return calls


def _set_manifesto(monkeypatch, mapping: dict):
    monkeypatch.setattr(express_signals, "manifesto_for", lambda name: mapping.get(name))


# ── _summarize ────────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_summarize_dict_is_compact_json():
    out = express_signals._summarize({"entries_written": 2, "path": "x.md"})
    assert_that('"entries_written": 2' in out, is_(True))


@pytest.mark.smoke
def test_summarize_str_is_whitespace_collapsed():
    assert_that(express_signals._summarize("a\n\n  b   c"), equal_to("a b c"))


@pytest.mark.smoke
def test_summarize_none_is_empty():
    assert_that(express_signals._summarize(None), equal_to(""))


@pytest.mark.smoke
def test_summarize_truncates_to_cap():
    big = "x" * 5000
    assert_that(len(express_signals._summarize(big)), equal_to(express_signals._MAX_SUMMARY))


# ── express_task_signal opt-in gate ───────────────────────────────────────────

@pytest.mark.smoke
def test_buffers_when_manifesto_opts_in(monkeypatch, captured):
    _set_manifesto(monkeypatch, {
        "workflows.hud.tasks.hud_logs.get_schedules": {
            "hfl_express": "buffer",
            "express_target": "rainmeter:SCHEDULES",
        },
    })
    doc_id = express_signals.express_task_signal(
        "workflows.hud.tasks.hud_logs.get_schedules", {"events": 3})
    assert_that(doc_id, not_none())
    assert_that(len(captured), equal_to(1))
    call = captured[0]
    assert_that(call["task"], equal_to("workflows.hud.tasks.hud_logs.get_schedules"))
    assert_that(call["source"], equal_to("signal:get_schedules"))
    assert_that(call["references"], equal_to(["rainmeter:SCHEDULES"]))
    assert_that('"events": 3' in call["summary"], is_(True))


@pytest.mark.smoke
def test_skips_when_hfl_express_absent(monkeypatch, captured):
    # hfl_signal True but no hfl_express → label only, no buffering.
    _set_manifesto(monkeypatch, {"some.task": {"hfl_signal": True}})
    assert_that(express_signals.express_task_signal("some.task", {"x": 1}), none())
    assert_that(len(captured), equal_to(0))


@pytest.mark.smoke
def test_skips_when_express_is_self(monkeypatch, captured):
    # The workflows/hfl/* ingestors self-express; the hook must not double-write.
    _set_manifesto(monkeypatch, {"hfl.task": {"hfl_express": "self"}})
    assert_that(express_signals.express_task_signal("hfl.task", {"x": 1}), none())
    assert_that(len(captured), equal_to(0))


@pytest.mark.smoke
def test_skips_when_no_manifesto(monkeypatch, captured):
    _set_manifesto(monkeypatch, {})
    assert_that(express_signals.express_task_signal("unknown.task", {"x": 1}), none())
    assert_that(len(captured), equal_to(0))


@pytest.mark.smoke
def test_skips_when_output_summarizes_empty(monkeypatch, captured):
    _set_manifesto(monkeypatch, {"t": {"hfl_express": "buffer"}})
    assert_that(express_signals.express_task_signal("t", None), none())
    assert_that(len(captured), equal_to(0))


# ── the signal receiver never raises ──────────────────────────────────────────

@pytest.mark.smoke
def test_on_task_success_swallows_errors(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("manifesto map exploded")

    monkeypatch.setattr(express_signals, "express_task_signal", _boom)

    class _Sender:
        name = "whatever.task"

    # Must not raise — a green task must stay green.
    express_signals._on_task_success(sender=_Sender(), result={"ok": True})
