"""Pending capture thresholds are hermetic: no model, broker, or Telegram IO."""
from datetime import datetime
from inspect import unwrap
from types import SimpleNamespace
from typing import Any, cast

import pytest

from workflows.dumps.files import CollectedFile
from workflows.hfl.tasks import monitor_pending_captures as monitor
from workflows.hfl.tasks.analyze_media import _acquire_media_claim, _finish_media_claim


def setup_capture(monkeypatch, tmp_path):
    inbox = tmp_path / "inbox"
    media = inbox / "windows-work-all-daily-dumps-2026-09-16" / "sc-desktop-check_monitor1.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"test")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    item = CollectedFile(source_root=inbox, path=media,
                         relative=media.relative_to(inbox), mtime=datetime.now())
    monkeypatch.setattr(monitor, "get_dumps_target", lambda: SimpleNamespace(inbox=inbox))
    monkeypatch.setattr(monitor, "resolve_corpus_dir", lambda: corpus)
    monkeypatch.setattr(monitor, "iter_recent_files", lambda *args: iter([item]))
    return media, corpus


@pytest.mark.parametrize("warning,critical,level", [(2, 3, "ok"), (1, 2, "warning"), (1, 1, "critical")])
def test_threshold_boundaries(monkeypatch, tmp_path, warning, critical, level):
    setup_capture(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(monitor, "_notify_telegram", lambda text: sent.append(text) or [42])
    result = monitor._monitor_pending_captures(warning_threshold=warning, critical_threshold=critical)
    assert result["sources"]["desktop"]["severity"] == level
    assert result["sources"]["android-capture"]["pending"] == 0
    assert result["telegram_message_ids"] == ([] if level == "ok" else [42])
    assert len(sent) == (0 if level == "ok" else 1)
    assert not sent or str(tmp_path) not in sent[0]


def test_skips_completed_and_active_claims(monkeypatch, tmp_path):
    media, corpus = setup_capture(monkeypatch, tmp_path)
    claim = _acquire_media_claim(corpus, media)
    assert claim is not None
    try:
        assert monitor._monitor_pending_captures(notify=False)["sources"]["desktop"]["pending"] == 0
    finally:
        _finish_media_claim(claim, completed=True)
    assert monitor._monitor_pending_captures(notify=False)["sources"]["desktop"]["pending"] == 0


def test_abandoned_claim_remains_pending(monkeypatch, tmp_path):
    media, corpus = setup_capture(monkeypatch, tmp_path)
    claim = _acquire_media_claim(corpus, media)
    assert claim is not None
    _finish_media_claim(claim, completed=False)
    assert monitor._monitor_pending_captures(notify=False)["sources"]["desktop"]["pending"] == 1


def test_missing_storage_not_healthy(monkeypatch):
    monkeypatch.setattr(monitor, "get_dumps_target", lambda: None)
    with pytest.raises(RuntimeError, match="inbox"):
        monitor._monitor_pending_captures()


def test_notification_failure_not_success(monkeypatch, tmp_path):
    setup_capture(monkeypatch, tmp_path)
    def fail(text):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(monitor, "_notify_telegram", fail)
    with pytest.raises(RuntimeError, match="unavailable"):
        monitor._monitor_pending_captures(warning_threshold=1)


def test_dry_notification_and_invalid_thresholds(monkeypatch, tmp_path):
    setup_capture(monkeypatch, tmp_path)
    monkeypatch.setattr(monitor, "_notify_telegram", lambda text: pytest.fail("sent"))
    assert not monitor._monitor_pending_captures(warning_threshold=1, notify=False)["ok"]
    with pytest.raises(ValueError):
        monitor._monitor_pending_captures(warning_threshold=0)


def test_desktop_schedule_and_defaults_match(monkeypatch):
    from workflows.hfl.tasks import analyze_desktop_capture as desktop
    from workflows.hfl.tasks_config import WORKFLOW_HFL
    calls = []
    monkeypatch.setattr(desktop, "analyze_hfl_media", lambda **kwargs: calls.append(kwargs) or {})
    unwrap(cast(Any, desktop.analyze_desktop_capture).run)()
    settings = WORKFLOW_HFL["run-job--analyze_desktop_capture"]["kwargs"]
    assert calls[0]["max_files"] == settings["max_files"] == 200
    assert calls[0]["window_days"] == settings["window_days"] == 7
    assert "run-job--monitor_pending_captures" in WORKFLOW_HFL
