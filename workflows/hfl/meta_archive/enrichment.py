"""Bounded, cached-in-work-item media enrichment for Meta archive events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from workflows.hfl.meta_archive.models import MetaEvent
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.analyze_media import _encode_image, _video_blocks
from workflows.hfl.tasks.ingest_plaud import _transcribe_with_whisper


def enrich_event_media(events: list[MetaEvent], *, allow_cloud: bool,
                       max_media: int = 12, frames_per_video: int = 4,
                       cache_dir: str = "",
                       cfg_id: str = "ANTHROPIC",
                       model: str = "claude-haiku-4-5-20251001",
                       whisper_model: str = "whisper-1") -> dict[str, dict[str, Any]]:
    """Caption/transcribe unique attachments; never raises for one bad artifact."""
    if not allow_cloud or max_media <= 0:
        return {}
    cache_root = Path(cache_dir).resolve() if cache_dir else None
    if cache_root:
        cache_root.mkdir(parents=True, exist_ok=True)
    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
    visual_ready = bool(getattr(client, "base_client", None))
    enriched: dict[str, dict[str, Any]] = {}
    for event in events:
        for attachment in event.attachments:
            key = attachment.media_id or attachment.path or attachment.uri
            if not key or key in enriched or len(enriched) >= max_media:
                continue
            cache_path = cache_root / f"{key}.json" if cache_root else None
            if cache_path and cache_path.exists():
                try:
                    enriched[key] = json.loads(cache_path.read_text(encoding="utf-8"))
                    continue
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            path = Path(attachment.path) if attachment.path else None
            result: dict[str, Any] = {"kind": attachment.kind, "reference": attachment.reference}
            if not path or not path.is_file():
                result["status"] = "missing"
                enriched[key] = result
                continue
            try:
                if attachment.kind in {"audio", "video"}:
                    transcript = _transcribe_with_whisper(str(path), model=whisper_model)
                    if transcript:
                        result["transcript"] = transcript[:20_000]
                if visual_ready and attachment.kind in {"image", "gif", "video", "sticker", "media"}:
                    blocks = _video_blocks(path, frames_per_video) if attachment.kind == "video" else []
                    if not blocks:
                        image = _encode_image(path)
                        blocks = [image] if image else []
                    if blocks:
                        instruction = {"type": "text", "text": "Describe this private Facebook/Instagram attachment factually and concisely. Do not infer identities or motives."}
                        response = client.send_messages(
                            messages=[{"role": "user", "content": [*blocks, instruction]}],
                            model=model, max_tokens=350,
                            system=load_prompt("meta_archive_media").strip(),
                        )
                        result["caption"] = (response.content[0].text if response and response.content else "")[:4000]
                result["status"] = "enriched" if result.get("caption") or result.get("transcript") else "metadata-only"
            except Exception as exc:  # noqa: BLE001 - enrichment is optional
                result.update(status="failed", error=type(exc).__name__)
            enriched[key] = result
            if cache_path:
                temporary = cache_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(cache_path)
    return enriched
