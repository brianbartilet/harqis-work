"""Desktop screenshot/image HFL capture task backed by the shared media engine."""

from __future__ import annotations

from typing import Any

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT

from workflows.hfl.tasks.analyze_media import _analyze_hfl_media as analyze_hfl_media


@SPROUT.task()
@log_result()
def analyze_desktop_capture(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = "claude-haiku-4-5-20251001",
    window_days: int = 1,
    max_files: int = 40,
    frames_per_video: int = 4,
    max_tokens: int = 1024,
    media_path: str | None = None,
) -> dict[str, Any]:
    return analyze_hfl_media(
        cfg_id__anthropic=cfg_id__anthropic,
        model=model,
        window_days=window_days,
        max_files=max_files,
        android_min_files=0,
        frames_per_video=frames_per_video,
        max_tokens=max_tokens,
        media_path=media_path,
        required_source="desktop",
        entry_source="desktop",
    )
