"""Cross-surface agent prompt/outcome audit ingestion and daily rollup.

Codex and Claude Code hooks, plus Hermes/OpenClaw/fallback adapters, submit a
versioned sanitized envelope. Each pair becomes one detailed local JSON
artifact and one canonical HFL entry (Markdown + Elasticsearch). A separate
23:40 task creates one rollup for the local calendar day.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from scripts.agents.hfl.capture_session_event import (
    audit_root,
    normalize_event,
    sanitize_text,
)
from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import is_canonical_machine, submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.ingest_git import _parse_model_json


_log = create_logger("hfl.ingest_agent_sessions")
_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def _brief_request(prompt: str, outcome: str = "", *, limit: int = 120) -> str:
    """Return a compact task-oriented Moment for no-model migrations."""
    text = " ".join(prompt.split()).strip(" -*#")
    text = re.sub(r"^(?:can|could|would) you\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^please\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bprompt audit\b", "prompt-audit", text, flags=re.IGNORECASE)
    if re.match(r"^\d+[.)]\s", text) and outcome:
        outcome_sentences = [
            part.strip(" -*")
            for part in re.split(r"(?<=[.!?])\s+|\n+", outcome)
            if part.strip(" -*")
        ]
        acknowledgements = {"got it", "okay", "ok", "sure", "done", "understood"}
        substantive = next(
            (
                sentence
                for sentence in outcome_sentences
                if sentence.casefold().rstrip(".!?") not in acknowledgements
                and not sentence.casefold().startswith(("let me ", "i'll ", "i will "))
            ),
            "",
        )
        if substantive:
            text = substantive
    clauses = [
        part.strip(" ,.?;")
        for part in re.split(r",\s*(?:and\s+)?", text)
        if part.strip()
    ]
    if len(text) > limit and len(clauses) > 1:
        first = re.sub(r"\s+readability$", "", clauses[0], flags=re.IGNORECASE)
        text = f"{first} and {clauses[-1]}"
    text = text.rstrip(".?!")
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return text[:1].upper() + text[1:] if text else "Agent task completed"


def _safe_markdown(text: str) -> str:
    """Preserve rich Markdown while reserving H2 for HFL entry navigation."""
    lines: list[str] = []
    in_fence = False
    for raw in (text or "").splitlines():
        stripped = raw.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            lines.append(raw.rstrip())
            continue
        if not in_fence:
            heading = re.match(r"^(\s*)#{1,6}\s+(.*)$", raw)
            if heading:
                raw = f"{heading.group(1)}#### {heading.group(2)}"
        lines.append(raw.rstrip())
    return "\n".join(lines).strip()


def _readable_markdown(text: str) -> str:
    """Preserve structured outcomes; bullet dense unstructured prose."""
    compact = _safe_markdown(text)
    if not compact:
        return "No visible outcome was retained."
    if any(
        line.lstrip().startswith(("- ", "* ", "+ ", "1. ", "#", "```", "~~~", "|"))
        for line in compact.splitlines()
    ):
        return compact
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", compact)
        if part.strip()
    ]
    return "\n".join(f"- {sentence}" for sentence in sentences)


def _short_line(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split()).strip(" -*")
    if len(compact) <= limit:
        return compact
    shortened = compact[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}…"


def _summarize_outcome(text: str, *, limit: int = 900) -> str:
    """Keep long fallback outcomes useful without cutting raw text mid-line."""
    normalized = "\n".join(
        " ".join(line.split())
        for line in (text or "").splitlines()
        if line.strip()
    )
    if len(normalized) <= limit:
        return normalized

    raw_lines = (text or "").splitlines()
    opening: list[str] = []
    for raw in raw_lines:
        line = raw.strip()
        if not line:
            if opening:
                break
            continue
        if not line.startswith(("|", "#")):
            opening.append(line)
    lead = _short_line(" ".join(opening), 240)
    lead = re.sub(
        r"^(?:yes|okay|ok|sure|understood)\.\s+",
        "",
        lead,
        flags=re.IGNORECASE,
    )

    headings: list[tuple[int, str]] = []
    for index, raw in enumerate(raw_lines):
        match = re.match(r"^\s*\d+[.)]\s+\*\*(.+?)\*\*", raw)
        if match:
            headings.append((index, match.group(1).strip()))

    highlights: list[str] = []
    before_ranked = raw_lines[: headings[0][0]] if headings else raw_lines
    for raw in before_ranked:
        total = re.match(
            r"^\s*\|\s*\*\*(.+?)\*\*\s*\|\s*\*\*(.+?)\*\*\s*\|\s*$",
            raw,
        )
        if total:
            highlights.append(f"- **{total.group(1)}:** {total.group(2)}")
        elif re.match(r"^\s*So\b", raw, re.IGNORECASE) and re.search(r"\d", raw):
            highlights.append(f"- {_short_line(raw)}")

    bullets: list[str] = []
    for position, (index, title) in enumerate(headings[:6]):
        stop = headings[position + 1][0] if position + 1 < len(headings) else len(raw_lines)
        details = []
        for raw in raw_lines[index + 1:stop]:
            detail = re.sub(r"^\s*[-*]\s+", "", raw).strip()
            if (
                detail
                and not detail.startswith(("|", "#", "`"))
                and not detail.endswith(":")
                and "[truncated]" not in detail.casefold()
            ):
                details.append(detail)
        if details:
            bullets.append(f"- **{title}:** {_short_line(details[-1])}")

    if not bullets:
        sentences = [
            _short_line(part)
            for part in re.split(r"(?<=[.!?])\s+|\n+", normalized)
            if part.strip() and "[truncated]" not in part.casefold()
        ]
        bullets = [f"- {sentence}" for sentence in sentences[1:6]]

    findings = [*highlights[:2], *bullets]
    lines = [lead, "", "Key findings:", *findings] if lead else ["Key findings:", *findings]
    selected: list[str] = []
    for line in lines:
        candidate = "\n".join([*selected, line]).strip()
        if len(candidate) > limit:
            break
        selected.append(line)
    return "\n".join(selected).strip()


def format_agent_session_happened(distilled: dict[str, Any]) -> str:
    """Render rich Markdown while avoiding H1/H2 navigation collisions."""
    request = " ".join(str(
        distilled.get("request_summary") or distilled.get("corrected_prompt") or ""
    ).split()).strip()
    request = re.sub(r"^#{1,6}\s+", "", request)
    outcome = _readable_markdown(str(distilled.get("work_summary") or ""))
    return f"### Request\n{request}\n\n### Outcome\n{outcome}"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _artifact_path(event: dict[str, Any]) -> Path:
    day = datetime.fromisoformat(event["timestamp"]).strftime("%Y-%m-%d")
    return audit_root() / "events" / day / f"{event['event_id']}.json"


def _fallback_distillation(event: dict[str, Any]) -> dict[str, Any]:
    corrected = " ".join(event["original_prompt"].split())
    outcome = _summarize_outcome(event["assistant_outcome"])
    return {
        "corrected_prompt": corrected,
        "request_summary": _brief_request(corrected, outcome),
        "work_summary": outcome,
        "result_status": event.get("result_status") or "unknown",
        "why_it_stayed": "Prompt and outcome retained for audit and future recall.",
        "tags": [],
        "synthesized": False,
    }


def distill_agent_session_event(
    event: dict[str, Any], *, synthesize: bool = True,
    model: str = _DEFAULT_HAIKU, cfg_id: str = "ANTHROPIC", max_tokens: int = 900,
) -> dict[str, Any]:
    fallback = _fallback_distillation(event)
    if not synthesize:
        return fallback
    model_input = json.dumps({
        "surface": event["surface"],
        "original_prompt": event["original_prompt"],
        "assistant_outcome": event["assistant_outcome"],
        "reported_status": event.get("result_status"),
        "artifacts": event.get("artifacts", []),
    }, ensure_ascii=False)
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return fallback
        response = client.send_message(
            prompt=model_input,
            system=load_prompt("ingest_agent_sessions").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        parsed = _parse_model_json(response.content[0].text if response and response.content else "")
        if not parsed:
            return fallback
        for key in ("corrected_prompt", "request_summary", "work_summary", "result_status", "why_it_stayed"):
            parsed[key] = sanitize_text(parsed.get(key) or fallback[key], limit=10_000)
        parsed["request_summary"] = _brief_request(
            parsed["request_summary"], parsed["work_summary"]
        )
        parsed["tags"] = [
            sanitize_text(tag, limit=100).lstrip("#")
            for tag in parsed.get("tags", [])
            if sanitize_text(tag, limit=100)
        ][:6]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001
        _log.warning("agent-session distillation failed (%s); using raw fallback", exc)
        return fallback


def collect_agent_session_events(
    *, since: date, until: date, limit: int = 500, processed_only: bool = False,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    root = audit_root() / "events"
    current = since
    while current <= until and len(events) < max(1, limit):
        for path in sorted((root / current.isoformat()).glob("*.json")) if (root / current.isoformat()).exists() else ():
            if path.name.startswith("._"):
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            ingest = item.get("ingest") if isinstance(item.get("ingest"), dict) else {}
            if processed_only and ingest.get("delivery") not in {"persisted", "forwarded", "outbox"}:
                continue
            item["artifact_path"] = str(path)
            events.append(item)
            if len(events) >= limit:
                break
        current += timedelta(days=1)
    events.sort(key=lambda item: item.get("timestamp", ""))
    return events


def _event_references(event: dict[str, Any], artifact_path: Path) -> tuple[str, ...]:
    refs = [str(artifact_path)]
    refs.extend(
        str(item["value"])
        for item in event.get("artifacts", [])
        if isinstance(item, dict)
        and item.get("kind") in {"url", "file", "path"}
        and item.get("value")
    )
    return tuple(dict.fromkeys(refs))


def process_agent_session_event(
    payload: dict[str, Any], *, source_artifact: str = "", synthesize: bool = True,
    model: str = _DEFAULT_HAIKU, cfg_id: str = "ANTHROPIC",
) -> dict[str, Any]:
    event = normalize_event(payload)
    if not event["original_prompt"] or not event["assistant_outcome"]:
        return {"skipped": "missing prompt or outcome", "entries_written": 0}
    path = _artifact_path(event)
    distilled = distill_agent_session_event(event, synthesize=synthesize, model=model, cfg_id=cfg_id)
    event.update({
        "corrected_prompt": distilled["corrected_prompt"],
        "request_summary": distilled["request_summary"],
        "work_summary": distilled["work_summary"],
        "result_status": distilled["result_status"],
        "source_artifact": source_artifact,
    })
    _atomic_json(path, event)
    when = datetime.fromisoformat(event["timestamp"]).replace(tzinfo=None)
    tags = tuple(dict.fromkeys([
        "prompt-audit", "ai-session", f"surface-{event['surface']}",
        event["result_status"], *event.get("tags", []), *distilled.get("tags", []),
    ]))
    entry = HflEntry(
        when=when,
        moment=distilled["request_summary"],
        what_happened=format_agent_session_happened(distilled),
        why_it_stayed=distilled["why_it_stayed"],
        possible_use="audit-log",
        tags=tags,
        references=_event_references(event, path),
    )
    persistence = submit_hfl_entry(
        entry, source="agent-session", synthesized=distilled["synthesized"],
        dedup_key=event["event_id"], es_doc_id=event["event_id"],
    )
    event["ingest"] = {**persistence, "synthesized": distilled["synthesized"], "processed_at": datetime.now().astimezone().isoformat()}
    _atomic_json(path, event)
    return {"entries_written": 1, "event_id": event["event_id"], "artifact": str(path), **persistence}


@SPROUT.task()
@log_result()
def ingest_agent_session_event(
    *, payload: dict[str, Any], source_artifact: str = "",
    cfg_id__anthropic: str = "ANTHROPIC", model: str = _DEFAULT_HAIKU,
) -> dict[str, Any]:
    try:
        return process_agent_session_event(payload, source_artifact=source_artifact, model=model, cfg_id=cfg_id__anthropic)
    except Exception as exc:  # noqa: BLE001
        _log.error("agent-session event ingest failed (%s)", exc)
        return {"skipped": "ingest failure", "entries_written": 0, "error": type(exc).__name__}


@SPROUT.task()
@log_result()
def ingest_agent_session_events(
    *, cfg_id__anthropic: str = "ANTHROPIC", model: str = _DEFAULT_HAIKU,
    window_days: int = 2, max_events: int = 500,
) -> dict[str, Any]:
    until = datetime.now().date()
    events = collect_agent_session_events(since=until - timedelta(days=max(0, window_days - 1)), until=until, limit=max_events)
    pending = [event for event in events if not event.get("ingest", {}).get("entry_id")]
    if not pending:
        return {"skipped": "no pending events", "entries_written": 0}
    if not is_canonical_machine():
        from workflows.queues import WorkflowQueue

        task_ids = []
        for event in pending:
            try:
                result = SPROUT.send_task(
                    "workflows.hfl.tasks.ingest_agent_sessions.ingest_agent_session_event",
                    kwargs={
                        "payload": event,
                        "source_artifact": event.get("artifact_path", ""),
                        "cfg_id__anthropic": cfg_id__anthropic,
                        "model": model,
                    },
                    queue=WorkflowQueue.HFL.value,
                )
                task_ids.append(str(result.id))
            except Exception as exc:  # noqa: BLE001
                _log.warning("agent-session retry forward failed (%s)", exc)
        return {
            "events_found": len(events),
            "entries_written": 0,
            "forwarded": len(task_ids),
            "task_ids": task_ids,
        }
    results = []
    for event in pending:
        try:
            results.append(process_agent_session_event(
                event, model=model, cfg_id=cfg_id__anthropic,
            ))
        except Exception as exc:  # noqa: BLE001
            _log.warning("agent-session retained event failed (%s)", exc)
            results.append({
                "skipped": "ingest failure",
                "entries_written": 0,
                "error": type(exc).__name__,
            })
    return {"events_found": len(events), "entries_written": sum(r.get("entries_written", 0) for r in results), "results": results}


def _fallback_rollup(events: list[dict[str, Any]], day: date) -> dict[str, Any]:
    surfaces = sorted({event.get("surface", "unknown") for event in events})
    completed = sum(event.get("result_status") == "completed" for event in events)
    lines = [f"- {event.get('request_summary') or event.get('corrected_prompt') or event.get('original_prompt', '')[:160]} [{event.get('result_status', 'unknown')}]" for event in events]
    return {
        "moment": f"{len(events)} agent prompt(s) audited across {', '.join(surfaces)}",
        "what_happened": "\n".join(lines[:30]),
        "why_it_stayed": f"{completed} completed outcome(s); durable prompt-level audit retained.",
        "possible_use": "audit-log",
        "tags": ["prompt-audit", "daily-rollup"],
        "synthesized": False,
    }


def distill_agent_session_rollup(events: list[dict[str, Any]], day: date, *, model: str, cfg_id: str) -> dict[str, Any]:
    fallback = _fallback_rollup(events, day)
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return fallback
        rows = [{key: event.get(key) for key in ("surface", "request_summary", "work_summary", "result_status")} for event in events]
        response = client.send_message(prompt=json.dumps({"date": day.isoformat(), "events": rows}, ensure_ascii=False), system=load_prompt("rollup_agent_sessions").strip(), model=model, max_tokens=1000)
        parsed = _parse_model_json(response.content[0].text if response and response.content else "")
        if not parsed:
            return fallback
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = sanitize_text(parsed.get(key) or fallback[key], limit=10_000)
        parsed["tags"] = [
            sanitize_text(tag, limit=100).lstrip("#")
            for tag in parsed.get("tags", [])
            if sanitize_text(tag, limit=100)
        ][:6]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001
        _log.warning("agent-session rollup failed (%s); using raw fallback", exc)
        return fallback


@SPROUT.task()
@log_result()
def rollup_agent_sessions(
    *, cfg_id__anthropic: str = "ANTHROPIC", model: str = _DEFAULT_HAIKU,
    day: Optional[str] = None, max_events: int = 500,
) -> dict[str, Any]:
    target = datetime.fromisoformat(day).date() if day else datetime.now().date()
    cutoff = datetime.combine(target, datetime.min.time()).replace(hour=23, minute=40)
    start = cutoff - timedelta(days=1)
    events = collect_agent_session_events(
        since=start.date(), until=target, limit=max_events, processed_only=True,
    )
    windowed = []
    for event in events:
        try:
            timestamp = datetime.fromisoformat(str(event["timestamp"])).replace(tzinfo=None)
        except (KeyError, TypeError, ValueError):
            continue
        if start < timestamp <= cutoff:
            windowed.append(event)
    events = windowed
    if not events:
        return {"skipped": "no agent session events", "entries_written": 0, "date": target.isoformat()}
    distilled = distill_agent_session_rollup(events, target, model=model, cfg_id=cfg_id__anthropic)
    when = cutoff
    surfaces = sorted({event.get("surface", "unknown") for event in events})
    refs = tuple(event["artifact_path"] for event in events[:100] if event.get("artifact_path"))
    entry = HflEntry(
        when=when, moment=distilled["moment"], what_happened=distilled["what_happened"],
        why_it_stayed=distilled["why_it_stayed"], possible_use=distilled["possible_use"] or "audit-log",
        tags=tuple(dict.fromkeys(["prompt-audit", "daily-rollup", *[f"surface-{surface}" for surface in surfaces], *distilled.get("tags", [])])),
        references=refs,
    )
    persistence = submit_hfl_entry(entry, source="agent-session-rollup", synthesized=distilled["synthesized"], dedup_key=target.isoformat(), es_doc_id=f"agent-session-rollup-{target:%Y%m%d}")
    return {"entries_written": 1, "events": len(events), "date": target.isoformat(), **persistence}
