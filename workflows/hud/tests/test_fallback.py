"""Unit tests for the HUD data-only fallback gate (workflows/hud/fallback.py).

Pure-logic + decorator tests — no live Elasticsearch. The ES read is stubbed by
monkeypatching ``get_index_data`` on the es_logging module (the gate imports it
lazily, so the patch is picked up at call time).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from workflows.hud import fallback
from workflows.hud.fallback import (
    _parse_heartbeat_date,
    windows_handled_recently,
    fallback_gate,
)


# ── _parse_heartbeat_date ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2026-05-27T19:42", datetime(2026, 5, 27, 19, 42)),
    ("2026-05-27T19:42:05", datetime(2026, 5, 27, 19, 42, 5)),
    ("2026-05-27T19:42:05.123456", datetime(2026, 5, 27, 19, 42, 5, 123456)),
    ("not-a-date", None),
    ("", None),
    (None, None),
])
def test__parse_heartbeat_date(raw, expected):
    assert _parse_heartbeat_date(raw) == expected


# ── windows_handled_recently ──────────────────────────────────────────────────

_TASK = "workflows.hud.tasks.hud_tcg.show_tcg_orders"


def _stub_es(monkeypatch, docs):
    """Patch get_index_data (imported lazily inside the gate) to return `docs`."""
    monkeypatch.setattr(
        "core.apps.es_logging.app.elasticsearch.get_index_data",
        lambda *a, **k: docs,
    )


def test__fresh_heartbeat_is_recent(monkeypatch):
    now = datetime(2026, 5, 27, 12, 0, 0)
    five_min_ago = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
    _stub_es(monkeypatch, [SimpleNamespace(name=_TASK, date=five_min_ago)])
    # threshold 1h → 5 min ago is fresh
    assert windows_handled_recently(_TASK, 3600, now=now) is True


def test__stale_heartbeat_is_not_recent(monkeypatch):
    now = datetime(2026, 5, 27, 12, 0, 0)
    two_hours_ago = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    _stub_es(monkeypatch, [SimpleNamespace(name=_TASK, date=two_hours_ago)])
    assert windows_handled_recently(_TASK, 3600, now=now) is False


def test__missing_doc_treated_as_stale(monkeypatch):
    _stub_es(monkeypatch, [SimpleNamespace(name="some.other.task", date="2026-05-27T11:59")])
    assert windows_handled_recently(_TASK, 3600) is False


def test__es_error_fails_open(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ES unreachable")
    monkeypatch.setattr("core.apps.es_logging.app.elasticsearch.get_index_data", boom)
    # fail-open → False (run the twin) rather than masking a down host
    assert windows_handled_recently(_TASK, 3600) is False


# ── fallback_gate decorator ───────────────────────────────────────────────────

def test__gate_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(fallback, "windows_handled_recently", lambda *a, **k: True)
    calls = []

    @fallback_gate(_TASK, 3600)
    def twin(**kwargs):
        calls.append(kwargs)
        return {"text": "DATA", "summary": "ran"}

    out = twin(cfg_id__tcg_mp="TCG_MP")
    assert out["skipped"] is True
    assert calls == []                      # inner collector never ran


def test__gate_runs_when_stale(monkeypatch):
    monkeypatch.setattr(fallback, "windows_handled_recently", lambda *a, **k: False)

    @fallback_gate(_TASK, 3600)
    def twin(**kwargs):
        return {"text": "DATA", "summary": "ran", "got": kwargs}

    out = twin(cfg_id__tcg_mp="TCG_MP")
    assert out["text"] == "DATA"
    assert out["got"] == {"cfg_id__tcg_mp": "TCG_MP"}   # control kwargs stripped


def test__gate_force_bypasses(monkeypatch):
    # Even if windows is fresh, force=True must run the collector.
    monkeypatch.setattr(fallback, "windows_handled_recently", lambda *a, **k: True)

    @fallback_gate(_TASK, 3600)
    def twin(**kwargs):
        return {"text": "FORCED"}

    out = twin(force=True)
    assert out["text"] == "FORCED"


def test__gate_staleness_override_is_consumed(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        fallback, "windows_handled_recently",
        lambda name, staleness, **k: seen.update(name=name, staleness=staleness) or False,
    )

    @fallback_gate(_TASK, 3600)
    def twin(**kwargs):
        return {"text": "DATA", "got": kwargs}

    out = twin(max_staleness_secs=7200, cfg_id__tcg_mp="TCG_MP")
    assert seen["staleness"] == 7200                    # override reached the gate
    assert out["got"] == {"cfg_id__tcg_mp": "TCG_MP"}   # not forwarded to collector
