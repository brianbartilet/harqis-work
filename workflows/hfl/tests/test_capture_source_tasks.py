from inspect import signature
from typing import Any, cast

import workflows.hfl  # noqa: F401 - registers Celery tasks
from core.apps.sprout.app.celery import SPROUT
from workflows.hfl.tasks import analyze_android_capture as android_mod
from workflows.hfl.tasks import analyze_desktop_capture as desktop_mod
from workflows.hfl.tasks_config import WORKFLOW_HFL


def test_desktop_task_constrains_shared_pipeline(monkeypatch):
    calls = []
    monkeypatch.setattr(
        desktop_mod,
        "analyze_hfl_media",
        lambda **kwargs: calls.append(kwargs) or {"entries_written": 1},
    )

    result = desktop_mod.analyze_desktop_capture(window_days=2, max_files=7)

    assert result == {"entries_written": 1}
    assert calls == [{
        "cfg_id__anthropic": "ANTHROPIC",
        "model": "claude-haiku-4-5-20251001",
        "window_days": 2,
        "max_files": 7,
        "android_min_files": 0,
        "frames_per_video": 4,
        "max_tokens": 1024,
        "media_path": None,
        "required_source": "desktop",
        "entry_source": "desktop",
    }]


def test_android_task_constrains_shared_pipeline(monkeypatch):
    calls = []
    monkeypatch.setattr(
        android_mod,
        "analyze_hfl_media",
        lambda **kwargs: calls.append(kwargs) or {"entries_written": 1},
    )

    result = android_mod.analyze_android_capture(window_days=3, max_files=10)

    assert result == {"entries_written": 1}
    assert calls[0]["required_source"] == "android_capture"
    assert calls[0]["entry_source"] == "android_capture"
    assert calls[0]["android_min_files"] == 0


def test_source_specific_tasks_replace_mixed_beat_entry():
    assert "run-job--analyze_hfl_media" not in WORKFLOW_HFL
    desktop = WORKFLOW_HFL["run-job--analyze_desktop_capture"]
    android = WORKFLOW_HFL["run-job--analyze_android_capture"]
    assert desktop["task"] == (
        "workflows.hfl.tasks.analyze_desktop_capture.analyze_desktop_capture"
    )
    assert android["task"] == (
        "workflows.hfl.tasks.analyze_android_capture.analyze_android_capture"
    )
    signature(desktop_mod.analyze_desktop_capture).bind_partial(**desktop["kwargs"])
    signature(android_mod.analyze_android_capture).bind_partial(**android["kwargs"])


def test_source_tasks_and_unscheduled_compatibility_task_are_registered():
    names = {
        "workflows.hfl.tasks.analyze_desktop_capture.analyze_desktop_capture",
        "workflows.hfl.tasks.analyze_android_capture.analyze_android_capture",
        "workflows.hfl.tasks.analyze_media.analyze_hfl_media",
    }

    assert names <= set(SPROUT.tasks)
    assert cast(Any, desktop_mod.analyze_desktop_capture).run.__wrapped__
    assert cast(Any, android_mod.analyze_android_capture).run.__wrapped__
    assert all(
        item["options"]["queue"].value == "hfl"
        for item in (
            WORKFLOW_HFL["run-job--analyze_desktop_capture"],
            WORKFLOW_HFL["run-job--analyze_android_capture"],
        )
    )
