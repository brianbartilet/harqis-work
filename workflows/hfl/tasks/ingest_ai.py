"""
workflows/hfl/tasks/ingest_ai.py

Daily AI-research → HFL corpus. Gathers the operator's own prompts /
research questions from their OpenAI assistant threads, distils them into
ONE Homework-for-Life entry, and appends it to the corpus so the day's
research flows into summarize_hfl_week and the memory_recall MCP
automatically.

Scope (per the approved spec): OpenAI assistant threads only. The
Anthropic API exposes no prompt-content history (only usage/cost
aggregates), so Anthropic is intentionally out of scope here — Claude is
used solely as the cost-bounded *distiller* (Haiku), never raised above
DEFAULT_MODEL.

The OpenAI Assistants API has NO list-threads endpoint — messages are only
retrievable per known thread id. The thread ids to inspect are resolved
from (first hit wins):
    1. the `thread_ids` kwarg (explicit list)
    2. env var OPENAI_HFL_THREAD_IDS (comma-separated)
No configured thread ids → no entry, no LLM call (mirrors
ingest_git_activity on a no-commit day). Only the operator's own
(`role == "user"`) messages are collected — their questions, not the
assistant's answers — bounded by:
  - messages_per_thread : page size per thread (Assistants list cap = 100)
  - max_messages        : hard cap on messages fed to the model

The collectors (collect_openai_activity / distill_ai_activity) are plain
functions so an MCP tool can reuse them for a live, no-write view.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.open_ai.config import CONFIG as OPENAI_CONFIG
from apps.open_ai.references.models.assistants.common import ListQuery
from apps.open_ai.references.services.assistants.messages import ServiceMessages

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import (
    _build_entry,
    append_entry,
    resolve_corpus_dir,
)
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_ai")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

# Assistants v2 list endpoint caps `limit` at 100.
_MAX_PAGE = 100


def _resolve_thread_ids(explicit: Optional[list[str]]) -> list[str]:
    """Resolve thread ids to inspect (kwarg → env), de-duplicated, order-stable."""
    raw: list[str] = []
    if explicit:
        raw = list(explicit)
    else:
        import os
        env = os.environ.get("OPENAI_HFL_THREAD_IDS", "").strip()
        if env:
            raw = env.split(",")
    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        tid = str(t).strip()
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


def _message_text(content: Any) -> str:
    """Flatten an Assistants v2 message `content` into plain text.

    v2 content is a list of blocks, each like
    {"type": "text", "text": {"value": "...", "annotations": [...]}}.
    Be defensive — dicts, objects, bare strings and Nones all occur in the
    wild — and silently drop non-text (image_file) blocks.
    """
    if not content:
        return ""
    if isinstance(content, str):
        return content.strip()
    blocks = content if isinstance(content, list) else [content]
    parts: list[str] = []
    for b in blocks:
        text = None
        if isinstance(b, dict):
            t = b.get("text")
            text = t.get("value") if isinstance(t, dict) else t
        else:
            t = getattr(b, "text", None)
            text = getattr(t, "value", None) if t is not None else None
            if isinstance(t, str) and text is None:
                text = t
        if text:
            parts.append(str(text).strip())
    return "\n".join(p for p in parts if p)


def collect_openai_activity(
    *,
    since: date,
    until: date,
    thread_ids: list[str],
    messages_per_thread: int = 50,
    max_messages: int = 300,
) -> dict[str, Any]:
    """List the operator's prompts in [since, until] across the given threads.

    Returns:
        {"threads": [{"thread_id", "messages": [{"when","text"}]}],
         "message_count", "thread_count"}
    """
    page = max(1, min(messages_per_thread, _MAX_PAGE))
    svc = ServiceMessages(OPENAI_CONFIG)

    groups: list[dict] = []
    total = 0
    for tid in thread_ids:
        if total >= max_messages:
            break
        kept: list[dict] = []
        after: Optional[str] = None
        stop = False
        while not stop and total < max_messages:
            query = ListQuery()
            query.limit = page
            query.order = "desc"  # newest first → can stop early past window
            if after:
                query.after = after
            try:
                resp = svc.get_messages(tid, query)
            except Exception as exc:  # noqa: BLE001 - skip a bad thread, keep going
                _log.info("ingest_ai: get_messages failed for %s (%s)", tid, exc)
                break
            data = getattr(resp, "data", None) or []
            if not data:
                break
            for m in data:
                ts = getattr(m, "created_at", None)
                if not ts:
                    continue
                d = datetime.fromtimestamp(int(ts))
                if d.date() < since:
                    stop = True  # desc order — nothing older can qualify
                    break
                if d.date() > until:
                    continue
                if (getattr(m, "role", "") or "").lower() != "user":
                    continue
                text = _message_text(getattr(m, "content", None))
                if not text:
                    continue
                kept.append({
                    "when": d.strftime("%Y-%m-%d %H:%M"),
                    "text": text[:2000],
                })
                total += 1
                if total >= max_messages:
                    break
            if stop or not getattr(resp, "has_more", False):
                break
            after = getattr(resp, "last_id", None)
            if not after:
                break
        if kept:
            kept.reverse()  # chronological within the thread
            groups.append({"thread_id": tid, "messages": kept})

    return {
        "threads": groups,
        "message_count": total,
        "thread_count": len(groups),
    }


def _activity_body(activity: dict) -> str:
    lines: list[str] = []
    for g in activity["threads"]:
        lines.append(f"### thread {g['thread_id']} ({len(g['messages'])} prompts)")
        for m in g["messages"]:
            lines.append(f"- {m['when']}  {m['text']}")
    return "\n".join(lines)


def distill_ai_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected prompts into HFL entry fields (Haiku, raw fallback)."""
    msg_count = activity["message_count"]
    thread_count = activity["thread_count"]

    def _fallback() -> dict:
        bullets = []
        for g in activity["threads"]:
            preview = "; ".join(m["text"][:80] for m in g["messages"][:6])
            bullets.append(
                f"- thread {g['thread_id']}: {len(g['messages'])} prompts — {preview}"
            )
        return {
            "skip": False,
            "moment": f"{msg_count} AI prompt(s) across {thread_count} thread(s)",
            "what_happened": "\n".join(bullets),
            "why_it_stayed": "",
            "possible_use": "research-log",
            "tags": ["ai", "research", "openai"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = (
        f"Operator prompts grouped by thread ({msg_count} total across "
        f"{thread_count} threads):\n\n{_activity_body(activity)}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_ai: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_ai").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_ai: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


@SPROUT.task()
@log_result()
def ingest_ai_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    thread_ids: Optional[list[str]] = None,
    messages_per_thread: int = 50,
    max_messages: int = 300,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's OpenAI research.

    No configured thread ids → no entry, no LLM call.
    No operator prompts in the window → no entry, no LLM call.
    """
    resolved = _resolve_thread_ids(thread_ids)
    if not resolved:
        _log.info("ingest_ai: no thread ids configured (kwarg/OPENAI_HFL_THREAD_IDS)")
        return {"skipped": "no thread ids", "entries_written": 0, "threads": 0}

    until = datetime.now().date()
    since = until - timedelta(days=window_days)

    try:
        activity = collect_openai_activity(
            since=since, until=until, thread_ids=resolved,
            messages_per_thread=messages_per_thread, max_messages=max_messages,
        )
    except Exception as exc:  # noqa: BLE001 - OpenAI down must not break beat
        _log.error("ingest_ai: OpenAI unavailable (%s)", exc)
        return {"skipped": "openai unavailable", "entries_written": 0,
                "error": str(exc)[:200]}

    if activity["message_count"] == 0:
        _log.info("ingest_ai: no operator prompts in last %d day(s)", window_days)
        return {"skipped": "no prompts", "entries_written": 0, "threads": 0}

    d = distill_ai_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info("ingest_ai: distilled as skip — %d prompts not story-worthy",
                  activity["message_count"])
        return {"skipped": "distilled-skip", "entries_written": 0,
                "message_count": activity["message_count"]}

    tags = ["ai", "research"] + [
        str(t) for t in (d.get("tags") or []) if str(t).strip()
    ][:6]

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"
    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "research-log",
        tags=tags,
    )
    append_entry(
        day_file, entry,
        source="ai", synthesized=d.get("synthesized", False),
    )

    _log.info("ingest_ai: entry written (%d prompts, %d threads) → %s",
              activity["message_count"], activity["thread_count"], day_file)
    return {
        "entries_written": 1,
        "threads": activity["thread_count"],
        "prompts": activity["message_count"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
    }
