"""Manual two-phase planner/dispatcher for downloaded Meta data exports."""

from __future__ import annotations

import hmac
import json
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from workflows.hfl.distill import parse_model_json
from workflows.hfl.dto import HflEntry, canonicalize_tags
from workflows.hfl.meta_archive.checkpoint import (
    TaskSnapshot, checkpoint_report, initialize_checkpoint, reconcile_items,
    reserve_items, update_item,
)
from workflows.hfl.meta_archive.enrichment import enrich_event_media
from workflows.hfl.meta_archive.models import MetaEvent, stable_hash
from workflows.hfl.meta_archive.planner import (
    build_import_plan,
    content_sha256,
    load_work_item,
)
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.queues import WorkflowQueue

_log = create_logger("hfl.ingest_meta_archive")
_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def _celery_task_snapshot(task_id: str) -> TaskSnapshot:
    """Read one task's durable Celery result without exposing its payload."""
    try:
        result = SPROUT.AsyncResult(task_id)
        state = str(result.state or "PENDING").upper()
        value = result.result
        return TaskSnapshot(
            state=state,
            result=value if isinstance(value, dict) else None,
            error=(type(value).__name__ if state in {"FAILURE", "REVOKED"} else ""),
        )
    except Exception as exc:  # noqa: BLE001 - recovery must remain inspectable
        return TaskSnapshot(state="UNKNOWN", error=type(exc).__name__)


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


def _validate_work_item(payload: dict[str, Any], events: list[MetaEvent],
                        *, platform: str) -> date:
    if payload.get("schema_version") != 2:
        raise ValueError("unsupported work item schema")
    if payload.get("platform") != platform:
        raise ValueError("work item platform mismatch")
    if not events:
        raise ValueError("work item contains no events")
    if any(event.platform != platform for event in events):
        raise ValueError("work item contains an event for another platform")
    if any(event.thread_id != payload.get("thread_id") for event in events):
        raise ValueError("work item contains an event for another thread")
    week_start = date.fromisoformat(str(payload["week_start"]))
    if week_start.weekday() != 0:
        raise ValueError("work item week_start must be an ISO Monday")
    if any((event.occurred_at_local.date() - week_start).days not in range(7)
           for event in events):
        raise ValueError("work item contains an event outside its ISO week")
    return week_start


def _ingest_meta_work_item(*, work_item_path: str, platform: str,
                          cfg_id__anthropic: str = "ANTHROPIC",
                          model: str = _DEFAULT_HAIKU, allow_cloud: bool = False,
                          max_media: int = 12, frames_per_video: int = 4,
                          whisper_model: str = "whisper-1",
                          synthesize: bool = False,
                          expected_work_item_sha256: str = "",
                          work_item_root: str = "") -> dict[str, Any]:
    payload, events = load_work_item(
        work_item_path,
        expected_sha256=expected_work_item_sha256,
        allowed_root=work_item_root,
    )
    week_start = _validate_work_item(payload, events, platform=platform)
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
    tags = canonicalize_tags([platform, "meta-archive", "weekly"] + [
        str(tag) for tag in distilled.get("tags") or [] if str(tag).strip()
    ][:6])
    # A stable date keeps overlapping exports in the same Markdown file. The
    # replacement policy below then atomically updates the exact stable-id block.
    entry_when = datetime.combine(
        week_start, time.min, tzinfo=events[0].occurred_at_local.tzinfo
    )
    entry = HflEntry(
        when=entry_when, moment=distilled["moment"],
        what_happened=distilled["what_happened"],
        why_it_stayed=distilled["why_it_stayed"],
        possible_use=distilled["possible_use"] or "timeline",
        tags=tuple(tags), references=references,
    )
    key = f"{platform}:{payload['thread_id']}:{payload['week_start']}"
    persistence = submit_hfl_entry(
        entry, source=platform, synthesized=bool(distilled.get("synthesized")),
        dedup_key=key, es_doc_id=f"meta-{platform}-{stable_hash(key)[:24]}",
        replace_duplicate=True,
    )
    if persistence.get("delivery") != "persisted" or persistence.get("indexed") is not True:
        raise RuntimeError(
            "Meta entry did not reach both canonical Markdown and Elasticsearch"
        )
    return {"entries_written": 1, "platform": platform,
            "thread_id": payload["thread_id"], "week_start": payload["week_start"],
            "events": len(events), "media_considered": len(enrichment),
            "synthesized": bool(distilled.get("synthesized")), "model": model,
            **persistence}


def ingest_meta_work_item(*, checkpoint_path: str = "", item_id: str = "",
                          **kwargs: Any) -> dict[str, Any]:
    """Persist one item and durably record its terminal dispatch outcome."""
    if checkpoint_path:
        item_root = Path(str(kwargs.get("work_item_root") or "")).expanduser().resolve()
        resolved_checkpoint = Path(checkpoint_path).expanduser().resolve()
        if not item_root or resolved_checkpoint.parent != item_root:
            raise ValueError("checkpoint is outside the approved work-item directory")
        checkpoint_path = str(resolved_checkpoint)
    try:
        result = _ingest_meta_work_item(**kwargs)
        if checkpoint_path and item_id:
            status = "distilled-skip" if result.get("skipped") == "distilled-skip" else "succeeded"
            update_item(checkpoint_path, item_id, status, result=result)
        return result
    except Exception as exc:
        if checkpoint_path and item_id:
            update_item(checkpoint_path, item_id, "failed", error=str(exc))
        raise


@SPROUT.task()
@log_result()
def prepare_meta_archive_import(*, platform: str, archive_roots: list[str],
                                work_dir: str, max_events: int = 500_000,
                                future_tolerance_hours: int = 24) -> dict:
    """Parse raw archives into resumable thread-week work items; writes no HFL."""
    try:
        return build_import_plan(platform=platform, archive_roots=archive_roots,
                                 work_dir=work_dir, max_events=max_events,
                                 future_tolerance_hours=future_tolerance_hours)
    except Exception as exc:  # noqa: BLE001
        _log.error("prepare_meta_archive_import failed (%s)", exc)
        return {"ok": False, "reason": "prepare-failed", "error": str(exc)[:300]}


def _approved_dispatch_items(*, manifest_path: str,
                             approved_manifest_sha256: str,
                             item_ids: list[str] | None = None
                             ) -> tuple[str, str, Path, list[dict[str, Any]]]:
    """Validate every reviewed artifact before any task can be enqueued."""
    manifest_file = Path(manifest_path).expanduser().resolve(strict=True)
    manifest_content = manifest_file.read_bytes()
    approved = approved_manifest_sha256.strip().casefold()
    if len(approved) != 64 or not hmac.compare_digest(
        content_sha256(manifest_content), approved
    ):
        raise ValueError("manifest integrity check failed")
    manifest = json.loads(manifest_content.decode("utf-8"))
    if (manifest.get("schema_version") != 2 or not manifest.get("ok")
            or not manifest.get("complete") or manifest.get("truncated")):
        raise ValueError("unsupported or unsuccessful Meta archive manifest")
    platform = manifest["platform"]
    if platform not in {"facebook", "instagram"}:
        raise ValueError("manifest platform must be facebook or instagram")
    work_root = manifest_file.parent.resolve(strict=True)
    quarantine = manifest.get("quarantine") or {}
    if quarantine.get("path") and quarantine.get("sha256"):
        quarantine_path = Path(str(quarantine["path"])).expanduser().resolve(strict=True)
        if not quarantine_path.is_relative_to(work_root):
            raise ValueError("quarantine report is outside the approved manifest directory")
        if not hmac.compare_digest(
            content_sha256(quarantine_path.read_bytes()), str(quarantine["sha256"]).casefold()
        ):
            raise ValueError("quarantine report integrity check failed")
        quarantine_payload = json.loads(quarantine_path.read_text(encoding="utf-8"))
        if (quarantine_payload.get("schema_version") != 2
                or quarantine_payload.get("platform") != platform
                or len(quarantine_payload.get("events") or []) != int(quarantine.get("count", -1))):
            raise ValueError("quarantine report metadata does not match the manifest")
    parser_failures = manifest.get("parser_failures") or {}
    if not parser_failures.get("path") or not parser_failures.get("sha256"):
        raise ValueError("manifest does not pin its parser-failure report")
    parser_failures_path = Path(
        str(parser_failures["path"])
    ).expanduser().resolve(strict=True)
    if not parser_failures_path.is_relative_to(work_root):
        raise ValueError("parser-failure report is outside the approved manifest directory")
    if not hmac.compare_digest(
        content_sha256(parser_failures_path.read_bytes()),
        str(parser_failures["sha256"]).casefold(),
    ):
        raise ValueError("parser-failure report integrity check failed")
    failures_payload = json.loads(parser_failures_path.read_text(encoding="utf-8"))
    failures = failures_payload.get("failures") or []
    if (failures_payload.get("schema_version") != 2
            or failures_payload.get("platform") != platform
            or len(failures) != int(parser_failures.get("count", -1))):
        raise ValueError("parser-failure report metadata does not match the manifest")
    if failures:
        raise ValueError("manifest contains unexplained parser failures")
    preparation_report = manifest.get("preparation_report") or {}
    if not preparation_report.get("path") or not preparation_report.get("sha256"):
        raise ValueError("manifest does not pin its preparation report")
    preparation_report_path = Path(
        str(preparation_report["path"])
    ).expanduser().resolve(strict=True)
    if not preparation_report_path.is_relative_to(work_root):
        raise ValueError("preparation report is outside the approved manifest directory")
    if not hmac.compare_digest(
        content_sha256(preparation_report_path.read_bytes()),
        str(preparation_report["sha256"]).casefold(),
    ):
        raise ValueError("preparation report integrity check failed")
    report_payload = json.loads(preparation_report_path.read_text(encoding="utf-8"))
    if (report_payload.get("schema_version") != 2
            or not report_payload.get("complete")
            or report_payload.get("truncated")
            or report_payload.get("platform") != platform
            or report_payload.get("counts") != manifest.get("counts")):
        raise ValueError("preparation report metadata does not match the manifest")
    approved_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in manifest.get("items") or []:
        if (not isinstance(item, dict) or not item.get("id")
                or not item.get("path") or not item.get("sha256")):
            raise ValueError("manifest contains an unpinned work item")
        if item["id"] in seen_ids:
            raise ValueError("manifest contains duplicate item IDs")
        seen_ids.add(str(item["id"]))
        payload, events = load_work_item(
            str(item["path"]), expected_sha256=str(item["sha256"]),
            allowed_root=str(work_root),
        )
        if (
            payload.get("item_id") != item.get("id")
            or
            payload.get("thread_id") != item.get("thread_id")
            or payload.get("week_start") != item.get("week_start")
            or len(events) != int(item.get("event_count", -1))
        ):
            raise ValueError("work item metadata does not match the approved manifest")
        _validate_work_item(payload, events, platform=platform)
        approved_items.append(item)
    if len(approved_items) != int(manifest.get("work_item_count", -1)):
        raise ValueError("manifest work-item count does not match its items")
    requested = set(item_ids or [])
    if requested and not requested.issubset(seen_ids):
        raise ValueError("requested item ID is not present in the approved manifest")
    return platform, approved, work_root, approved_items


@SPROUT.task()
@log_result()
def dispatch_meta_archive_import(*, manifest_path: str,
                                 approved_manifest_sha256: str,
                                 allow_cloud: bool = False,
                                 synthesize: bool = False,
                                 max_items: int = 100,
                                 item_ids: list[str] | None = None,
                                 retry_failed: bool = False,
                                 reservation_lease_seconds: int = 300,
                                 enqueued_lease_seconds: int = 21_600) -> dict:
    """Dispatch only the exact manifest and work items approved by review."""
    try:
        platform, approved, work_root, approved_items = _approved_dispatch_items(
            manifest_path=manifest_path,
            approved_manifest_sha256=approved_manifest_sha256,
            item_ids=item_ids,
        )
        checkpoint_path = work_root / "dispatch.sqlite3"
        initialize_checkpoint(
            checkpoint_path, manifest_sha256=approved, platform=platform,
            items=approved_items, allow_cloud=allow_cloud, synthesize=synthesize,
        )
        recovery = reconcile_items(
            checkpoint_path, _celery_task_snapshot,
            active_lease_seconds=enqueued_lease_seconds,
        )
        selected_ids = reserve_items(
            checkpoint_path, max_items=min(max(0, int(max_items)), 10_000),
            item_ids=item_ids, retry_failed=retry_failed,
            lease_seconds=reservation_lease_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed before any dispatch
        _log.warning("Meta archive dispatch rejected (%s)", exc)
        return {
            "ok": False,
            "reason": "integrity-check-failed",
            "error": str(exc)[:200],
            "dispatched": 0,
            "task_ids": [],
        }
    task_name = f"workflows.hfl.tasks.ingest_{platform}.ingest_{platform}_activity"
    by_id = {str(item["id"]): item for item in approved_items}
    task_ids: list[str] = []
    for item_id in selected_ids:
        item = by_id[item_id]
        task_id = str(uuid.uuid4())
        try:
            update_item(
                checkpoint_path, item_id, "dispatching", task_id=task_id,
                lease_seconds=reservation_lease_seconds,
            )
            result = SPROUT.send_task(
                task_name,
                kwargs={
                    "work_item_path": item["path"],
                    "expected_work_item_sha256": item["sha256"],
                    "work_item_root": str(work_root),
                    "allow_cloud": allow_cloud,
                    "synthesize": synthesize,
                    "checkpoint_path": str(checkpoint_path),
                    "item_id": item_id,
                },
                queue=WorkflowQueue.HFL.value, task_id=task_id,
            )
            actual_task_id = str(result.id or task_id)
            update_item(
                checkpoint_path, item_id, "enqueued", task_id=actual_task_id,
                lease_seconds=enqueued_lease_seconds,
            )
            task_ids.append(actual_task_id)
        except Exception as exc:
            update_item(checkpoint_path, item_id, "failed", task_id=task_id, error=str(exc))
            _log.error("failed to enqueue Meta item %s (%s)", item_id, exc)
    report = checkpoint_report(checkpoint_path)
    return {
        "ok": len(task_ids) == len(selected_ids),
        "reason": "" if len(task_ids) == len(selected_ids) else "enqueue-failed",
        "platform": platform,
        "manifest_sha256": approved,
        "allow_cloud": bool(allow_cloud),
        "synthesize": bool(synthesize),
        "dispatched": len(task_ids),
        "task_ids": task_ids,
        "checkpoint_path": str(checkpoint_path),
        "estimated_synthesis_calls": len(task_ids) if synthesize else 0,
        "recovery": recovery,
        **report,
    }


@SPROUT.task()
@log_result()
def recover_meta_archive_import(*, manifest_path: str,
                                approved_manifest_sha256: str,
                                reclaim_pending: bool = False,
                                active_lease_seconds: int = 21_600) -> dict:
    """Reconcile leases; optionally fail expired ambiguous tasks for retry."""
    try:
        _, approved, work_root, _ = _approved_dispatch_items(
            manifest_path=manifest_path,
            approved_manifest_sha256=approved_manifest_sha256,
        )
        checkpoint_path = work_root / "dispatch.sqlite3"
        transitions = reconcile_items(
            checkpoint_path, _celery_task_snapshot,
            active_lease_seconds=active_lease_seconds,
            reclaim_pending=reclaim_pending,
        )
        report = checkpoint_report(checkpoint_path)
        if not hmac.compare_digest(report["manifest_sha256"], approved):
            raise ValueError("checkpoint manifest pin does not match approval")
        return {"ok": True, "checkpoint_path": str(checkpoint_path),
                "transitions": transitions, **report}
    except Exception as exc:
        return {"ok": False, "reason": "recovery-failed", "error": str(exc)[:200]}


@SPROUT.task()
@log_result()
def report_meta_archive_import(*, manifest_path: str,
                               approved_manifest_sha256: str) -> dict:
    """Write and return an auditable snapshot of dispatch outcomes."""
    try:
        _, approved, work_root, _ = _approved_dispatch_items(
            manifest_path=manifest_path,
            approved_manifest_sha256=approved_manifest_sha256,
        )
        checkpoint_path = work_root / "dispatch.sqlite3"
        transitions = reconcile_items(
            checkpoint_path, _celery_task_snapshot,
        )
        report = {"ok": True, "generated_at": datetime.now().astimezone().isoformat(),
                  "checkpoint_path": str(checkpoint_path),
                  "recovery": transitions,
                  **checkpoint_report(checkpoint_path)}
        if not hmac.compare_digest(report["manifest_sha256"], approved):
            raise ValueError("checkpoint manifest pin does not match approval")
        report_path = work_root / "final-report.json"
        content = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_bytes(content)
        temporary.replace(report_path)
        return {**report, "report_path": str(report_path),
                "report_sha256": content_sha256(content)}
    except Exception as exc:
        return {"ok": False, "reason": "report-failed", "error": str(exc)[:200]}
