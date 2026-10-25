"""Selected Granola meeting summaries -> one durable HFL entry per note.

GRANOLA_API_KEY authenticates the official service. GRANOLA_FOLDER_ID selects
the import folder (including descendants). Missing credentials/folder or empty
windows are clean no-ops. No transcript/private notes are fetched for ingestion.
Initial capture only: existing entries are deduplicated, never overwritten.
Manual backfills use inclusive Singapore created-date windows and opaque cursors.
All writes use submit_hfl_entry, including canonical forwarding/outbox fallback.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger
from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.granola.config import CONFIG
from apps.granola.references.web.base_api_service import configured_api_key
from apps.granola.references.web.api.notes import ApiServiceGranolaNotes, resource_id
from workflows.hfl.distill import parse_model_json
from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt

_log = create_logger("hfl.ingest_granola")
_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_SGT = ZoneInfo("Asia/Singapore")


def _datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(_SGT) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _folder(value):
    value = str(value or os.environ.get("GRANOLA_FOLDER_ID", "")).strip()
    return "" if value.startswith("${") else value


def collect_granola_activity(*, since: date, until: date, folder_id="",
                             service=None, max_notes=20, max_pages=5, cursor=""):
    """Read bounded pages in an inclusive created-date window; no writes/LLM."""
    if since > until or not 1 <= max_notes <= 100 or not 1 <= max_pages <= 20:
        raise ValueError("Invalid date window or collection bounds")
    selected_folder = _folder(folder_id)
    result = {"notes": [], "errors": [], "partial": False, "next_cursor": cursor,
              "since": since.isoformat(), "until": until.isoformat()}
    if not selected_folder:
        return {**result, "skipped": "no folder"}
    resource_id(selected_folder, "fol")
    if service is None:
        if not configured_api_key(CONFIG):
            return {**result, "skipped": "no token"}
        service = ApiServiceGranolaNotes(CONFIG)
    lower = datetime.combine(since, time.min, _SGT)
    upper = datetime.combine(until + timedelta(days=1), time.min, _SGT)
    seen, cursors = set(), {cursor}
    for _ in range(max_pages):
        request_cursor = cursor
        page_size = min(20, max_notes - len(result["notes"]))
        try:
            response = service.list_notes(
                created_after=(lower - timedelta(microseconds=1)).astimezone(timezone.utc).isoformat(),
                created_before=upper.astimezone(timezone.utc).isoformat(),
                folder_id=selected_folder, cursor=cursor,
                page_size=page_size,
            )
            if len(response["notes"]) > page_size:
                raise ValueError("Granola page exceeds requested limit")
        except Exception as exc:
            result["errors"].append(type(exc).__name__)
            result.update(partial=True, next_cursor=request_cursor)
            break
        for item in response["notes"]:
            try:
                note_id = resource_id(item["id"], "not")
                if note_id in seen or item.get("deleted_at"):
                    continue
                seen.add(note_id)
                note = service.get_note(note_id)
                created = _datetime(note.created_at)
                if note.deleted_at or not created or not lower <= created < upper:
                    continue
                summary = note.summary_markdown or note.summary_text or ""
                if not isinstance(summary, str) or not summary.strip():
                    continue
                event = note.calendar_event if isinstance(note.calendar_event, dict) else {}
                event_time = _datetime(event.get("scheduled_start_time")) or created
                url = str(note.web_url or "")
                # Store a reference, never fetch a URL supplied by a note.
                if not url.startswith("https://notes.granola.ai/"):
                    url = f"granola:{note_id}"
                result["notes"].append({
                    "id": note_id, "title": str(note.title or "Granola meeting")[:200],
                    "summary": summary[:30000], "truncated": len(summary) > 30000,
                    # Creation time is stable across calendar rescheduling.
                    # Store the meeting time separately as source metadata.
                    "when": created.isoformat(), "meeting_at": event_time.isoformat(),
                    "created_at": created.isoformat(),
                    "updated_at": note.updated_at, "reference": url,
                })
            except Exception as exc:
                result["errors"].append(type(exc).__name__)
        cursor = response.get("cursor") or ""
        # Do not advance past a page with failed details. Replaying it is safe.
        if result["errors"]:
            result.update(partial=True, next_cursor=request_cursor)
            break
        if not response["hasMore"]:
            result["next_cursor"] = ""
            break
        result.update(partial=True, next_cursor=cursor)
        if not cursor or cursor in cursors:
            result["errors"].append("RepeatedCursor")
            break
        cursors.add(cursor)
        if len(result["notes"]) >= max_notes:
            break
        result["partial"] = False
    else:
        result["partial"] = True
    return result


def distill_granola_activity(activity, *, synthesize=True, model=_DEFAULT_HAIKU,
                            cfg_id="ANTHROPIC", max_tokens=900):
    """Distil one collected note; malformed/failed output uses labelled source text."""
    fallback = {
        "skip": False, "moment": activity["title"][:120],
        "what_happened": "Granola AI summary (not a verbatim transcript):\n\n" + activity["summary"],
        "why_it_stayed": "", "possible_use": "meeting-recall",
        "tags": ["granola", "meeting"], "synthesized": True,
        "distilled": False,
    }
    # Source summaries are already synthesized, even when HARQIS adds no LLM pass.
    if not synthesize:
        return fallback
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        response = client.send_message(
            prompt=json.dumps(activity, ensure_ascii=False),
            system=load_prompt("ingest_granola"), model=model, max_tokens=max_tokens,
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        data = parse_model_json(text)
        if type(data.get("skip")) is not bool:
            return fallback
        if data["skip"]:
            return {**fallback, "skip": True}
        keys = ("moment", "what_happened", "why_it_stayed", "possible_use")
        if (any(not isinstance(data.get(k), str) for k in keys)
                or not data["moment"].strip() or not data["what_happened"].strip()
                or not isinstance(data.get("tags"), list)
                or any(not isinstance(tag, str) for tag in data["tags"])
                or getattr(response, "stop_reason", "") == "max_tokens"):
            return fallback
        return {
            **{k: data[k].strip()[:4000] for k in keys},
            "moment": data["moment"].strip()[:120], "skip": False,
            "tags": [t.strip().lstrip("#")[:60] for t in data["tags"][:6]],
            "synthesized": True, "distilled": True,
        }
    except Exception as exc:
        _log.warning("Granola distillation fallback: %s", type(exc).__name__)
        return fallback


@SPROUT.task()
@log_result()
def ingest_granola_activity(*, cfg_id__anthropic="ANTHROPIC", model=_DEFAULT_HAIKU,
                           window_days=7, since="", until="", folder_id="",
                           max_notes=20, max_pages=5, cursor="", synthesize=True):
    """Capture each selected meeting once; report canonical delivery separately."""
    if not configured_api_key(CONFIG):
        return {"skipped": "no token", "entries_written": 0}
    if not _folder(folder_id):
        return {"skipped": "no folder", "entries_written": 0}
    try:
        if not 1 <= window_days <= 366:
            raise ValueError("window_days must be 1–366")
        end = date.fromisoformat(until) if until else datetime.now(_SGT).date()
        start = date.fromisoformat(since) if since else end - timedelta(days=window_days - 1)
        activity = collect_granola_activity(
            since=start, until=end, folder_id=folder_id, max_notes=max_notes,
            max_pages=max_pages, cursor=cursor,
        )
    except Exception as exc:
        return {"skipped": "collection failed", "entries_written": 0,
                "error": type(exc).__name__, "partial": True}
    results = []
    for note in activity["notes"]:
        distilled = distill_granola_activity(
            note, synthesize=synthesize, model=model, cfg_id=cfg_id__anthropic,
        )
        if distilled["skip"]:
            continue
        source_notice = "\n\nProvenance: Granola AI-generated meeting summary."
        source_notice += f" Meeting time: {note['meeting_at']}."
        if note["truncated"]:
            source_notice += " Input truncated to 30,000 characters."
        entry = HflEntry(
            when=_datetime(note["when"]), moment=distilled["moment"],
            what_happened=distilled["what_happened"] + source_notice,
            why_it_stayed=distilled["why_it_stayed"], possible_use=distilled["possible_use"],
            tags=["granola", "meeting", *distilled["tags"]],
            references=[note["reference"]],
        )
        try:
            receipt = submit_hfl_entry(
                entry, source="granola", synthesized=distilled["synthesized"],
                dedup_key=f"granola:{note['id']}",
            )
            results.append({**receipt, "note_id": note["id"],
                            "distilled": distilled["distilled"],
                            "model": model if distilled["distilled"] else None})
        except Exception as exc:
            results.append({"note_id": note["id"], "delivery": "failed",
                            "error": type(exc).__name__})
    return {
        "entries_written": sum(r.get("delivery") == "persisted" and not r.get("duplicate") for r in results),
        "entries_submitted": len(results), "notes": len(activity["notes"]),
        "skipped": "no notes" if not activity["notes"] and not activity["errors"] else "",
        "partial": activity["partial"] or any(r.get("delivery") in {"failed", "outbox"} for r in results),
        "errors": activity["errors"], "next_cursor": activity["next_cursor"],
        "since": activity["since"], "until": activity["until"], "results": results,
    }
