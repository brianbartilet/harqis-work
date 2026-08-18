"""Manual two-phase planner/dispatcher for downloaded Meta data exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from workflows.hfl.distill import parse_model_json
from workflows.hfl.dto import HflEntry
from workflows.hfl.meta_archive.enrichment import enrich_event_media
from workflows.hfl.meta_archive.models import MetaEvent, stable_hash
from workflows.hfl.meta_archive.planner import build_import_plan, load_work_item
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.queues import WorkflowQueue

_log = create_logger("hfl.ingest_meta_archive")
_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def render_activity(events: list[MetaEvent], enrichment: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    for event in events:
        body = " ".join(event.content.split())[:1600] or f"[{event.event_type}]"
        lines.append(f"- {event.occurred_at_local:%Y-%m-%d %H:%M} — {event.sender}: {body}")
        for attachment in event.attachments:
            context = enrichment.get(attachment.media_id or attachment.path or attachment.uri, {})
            detail = context.get("transcript") or context.get("caption") or attachment.title
            if detail:
                lines.append(f"  - {attachment.kind}: {' '.join(str(detail).split())[:1600]}")
    return "\n".join(lines)[:60_000]


def distill_meta_activity(events: list[MetaEvent], *, platform: str,
                          enrichment: dict[str, dict[str, Any]] | None = None,
                          synthesize: bool = True, cfg_id: str = "ANTHROPIC",
                          model: str = _DEFAULT_HAIKU,
                          max_tokens: int = 900) -> dict[str, Any]:
    enrichment = enrichment or {}
    title = events[0].thread_title if events else ""
    body = render_activity(events, enrichment)

    def fallback() -> dict[str, Any]:
        return {"skip": not bool(events),
                "moment": f"{len(events)} {platform} interaction(s) with {title}"[:120],
                "what_happened": body, "why_it_stayed": "",
                "possible_use": "timeline", "tags": [platform, "conversation"],
                "synthesized": False}

    if not synthesize or not events:
        return fallback()
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return fallback()
        response = client.send_message(
            prompt=f"Platform: {platform}\nConversation: {title}\n\n{body}",
            system=load_prompt(f"ingest_{platform}").strip(), model=model,
            max_tokens=max_tokens,
        )
        parsed = parse_model_json(response.content[0].text if response and response.content else "")
        if not parsed:
            return fallback()
        parsed.setdefault("skip", False)
        for field in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[field] = str(parsed.get(field) or "").strip()
        parsed["tags"] = [str(tag).strip().lstrip("#") for tag in parsed.get("tags") or []]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - manual backfill stays resumable
        _log.warning("meta archive distillation failed (%s)", exc)
        return fallback()


def ingest_meta_work_item(*, work_item_path: str, platform: str,
                          cfg_id__anthropic: str = "ANTHROPIC",
                          model: str = _DEFAULT_HAIKU, allow_cloud: bool = True,
                          max_media: int = 12, frames_per_video: int = 4,
                          whisper_model: str = "whisper-1",
                          synthesize: bool = True) -> dict[str, Any]:
    payload, events = load_work_item(work_item_path)
    if payload.get("platform") != platform:
        return {"skipped": "platform mismatch", "entries_written": 0}
    if not events:
        return {"skipped": "no events", "entries_written": 0}
    enrichment = enrich_event_media(
        events, allow_cloud=allow_cloud, max_media=max_media,
        frames_per_video=frames_per_video, cfg_id=cfg_id__anthropic,
        model=model, whisper_model=whisper_model,
        cache_dir=str(Path(work_item_path).resolve().parent / "media-cache"),
    )
    distilled = distill_meta_activity(
        events, platform=platform, enrichment=enrichment,
        synthesize=synthesize, cfg_id=cfg_id__anthropic, model=model,
    )
    if distilled.get("skip"):
        return {"skipped": "distilled-skip", "entries_written": 0}
    references = tuple(dict.fromkeys(
        reference for event in events for reference in event.references
    ))[:25]
    tags = [platform, "meta-archive", "weekly"] + [
        str(tag) for tag in distilled.get("tags") or [] if str(tag).strip()
    ][:6]
    latest = max(event.occurred_at_local for event in events)
    entry = HflEntry(
        when=latest, moment=distilled["moment"],
        what_happened=distilled["what_happened"],
        why_it_stayed=distilled["why_it_stayed"],
        possible_use=distilled["possible_use"] or "timeline",
        tags=tuple(tags), references=references,
    )
    key = f"{platform}:{payload['thread_id']}:{payload['week_start']}"
    persistence = submit_hfl_entry(
        entry, source=platform, synthesized=bool(distilled.get("synthesized")),
        dedup_key=key, es_doc_id=f"meta-{platform}-{stable_hash(key)[:24]}",
    )
    return {"entries_written": 1, "platform": platform,
            "thread_id": payload["thread_id"], "week_start": payload["week_start"],
            "events": len(events), "media_considered": len(enrichment),
            "synthesized": bool(distilled.get("synthesized")), "model": model,
            **persistence}


@SPROUT.task()
@log_result()
def prepare_meta_archive_import(*, platform: str, archive_roots: list[str],
                                work_dir: str, max_events: int = 500_000) -> dict:
    """Parse raw archives into resumable thread-week work items; writes no HFL."""
    try:
        return build_import_plan(platform=platform, archive_roots=archive_roots,
                                 work_dir=work_dir, max_events=max_events)
    except Exception as exc:  # noqa: BLE001
        _log.error("prepare_meta_archive_import failed (%s)", exc)
        return {"ok": False, "reason": "prepare-failed", "error": str(exc)[:300]}


@SPROUT.task()
@log_result()
def dispatch_meta_archive_import(*, manifest_path: str, allow_cloud: bool = True,
                                 max_items: int = 10_000) -> dict:
    """Dispatch prepared work items; leaf tasks own all durable HFL writes."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    platform = manifest["platform"]
    task_name = f"workflows.hfl.tasks.ingest_{platform}.ingest_{platform}_activity"
    task_ids: list[str] = []
    for item in (manifest.get("items") or [])[:max_items]:
        result = SPROUT.send_task(
            task_name, kwargs={"work_item_path": item["path"], "allow_cloud": allow_cloud},
            queue=WorkflowQueue.HFL.value,
        )
        task_ids.append(str(result.id))
    return {"platform": platform, "dispatched": len(task_ids), "task_ids": task_ids}
