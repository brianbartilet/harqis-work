#!/usr/bin/env python3
"""Migrate closed Hermes CLI/Telegram turns into HFL prompt-audit events."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agents.hfl.capture_session_event import normalize_event


DEFAULT_DB = Path.home() / ".hermes" / "state.db"
DEFAULT_SOURCES = ("cli", "telegram")

_INTERNAL_USER_PREFIXES = (
    "[async delegation batch complete",
    "[context compaction",
    "[system:",
    "[your active task list",
    "you've reached the maximum number of tool-calling iterations",
)
_LOW_VALUE_CONTROL = {"stop", "cancel", "nevermind", "never mind", "thanks", "thank you"}
_LOW_VALUE_CONFIRMATION = re.compile(
    r"^(?:yes(?:[,.! ]+approve)?|approved?|ok(?:ay)?|confirm(?:ed)?|proceed|go ahead|continue|do it)(?:[,.! ]+please)?[.!?]*$",
    re.IGNORECASE,
)


def _user_message_kind(content: str) -> str:
    normalized = " ".join(content.casefold().split())
    if _is_internal_context(normalized):
        return "internal"
    if normalized.rstrip(".!?") in _LOW_VALUE_CONTROL or _LOW_VALUE_CONFIRMATION.fullmatch(normalized):
        return "discard"
    return "prompt"


def _is_internal_context(content: str) -> bool:
    normalized = " ".join(content.casefold().split())
    return any(normalized.startswith(prefix) for prefix in _INTERNAL_USER_PREFIXES)


def _strip_appended_internal_context(content: str) -> str:
    lowered = content.casefold()
    positions = [
        position
        for prefix in _INTERNAL_USER_PREFIXES
        if (position := lowered.find(prefix)) > 0
    ]
    return content[: min(positions)].rstrip() if positions else content


def collect_session_pairs(
    database: Path,
    *,
    sources: Iterable[str] = DEFAULT_SOURCES,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict]:
    """Read closed user-facing sessions and pair each prompt with its next visible outcome."""
    source_values = tuple(dict.fromkeys(str(source) for source in sources))
    if not source_values:
        return []
    connection = sqlite3.connect(f"file:{Path(database).expanduser().resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in source_values)
    rows = connection.execute(
        f"""
        SELECT m.id, m.session_id, m.role, m.content, m.timestamp,
               COALESCE(m.active, 1) AS active,
               COALESCE(m.compacted, 0) AS compacted,
               s.source
          FROM messages AS m
          JOIN sessions AS s ON s.id = m.session_id
         WHERE s.ended_at IS NOT NULL
           AND s.source IN ({placeholders})
         ORDER BY m.session_id, m.id
        """,
        source_values,
    ).fetchall()
    connection.close()

    lower = since.timestamp() if since else None
    upper = until.timestamp() if until else None
    raw_pairs: list[dict] = []
    session_id = None
    pending = None
    pending_kind = None
    last_pair = None
    for row in rows:
        if row["session_id"] != session_id:
            session_id = row["session_id"]
            pending = None
            pending_kind = None
            last_pair = None
        if not row["active"] or row["compacted"]:
            continue
        content = str(row["content"] or "").strip()
        if not _is_internal_context(content):
            content = _strip_appended_internal_context(content)
        if row["role"] == "user" and content:
            pending = dict(row)
            pending["content"] = content
            pending_kind = _user_message_kind(content)
            continue
        if row["role"] == "assistant" and _is_internal_context(content):
            continue
        if row["role"] != "assistant" or not content or pending is None:
            continue
        if pending_kind == "internal":
            if last_pair is not None:
                last_pair["assistant_outcome"] += f"\n\n{content}"
            pending = None
            pending_kind = None
            continue
        if pending_kind == "discard":
            pending = None
            pending_kind = None
            continue
        timestamp = pending["timestamp"]
        if timestamp is None or (lower is not None and timestamp < lower) or (
            upper is not None and timestamp > upper
        ):
            pending = None
            continue
        raw = {
            "surface": "hermes",
            "session_id": pending["session_id"],
            "prompt_id": str(pending["id"]),
            "timestamp": datetime.fromtimestamp(timestamp).astimezone().isoformat(),
            "original_prompt": str(pending["content"] or ""),
            "assistant_outcome": content,
            "result_status": "unknown",
            "tags": [f"hermes-{pending['source']}"],
        }
        raw_pairs.append(raw)
        last_pair = raw
        pending = None
        pending_kind = None
    normalized = [normalize_event(raw, surface="hermes") for raw in raw_pairs]
    normalized.sort(key=lambda pair: (pair["timestamp"], pair["session_id"], pair["prompt_id"]))
    from workflows.hfl.tasks.ingest_agent_sessions import (
        distill_agent_session_event,
        format_agent_session_happened,
    )

    seen: set[tuple[str, str]] = set()
    seen_visible: set[str] = set()
    unique = []
    for pair in normalized:
        signature = (
            " ".join(str(pair["original_prompt"]).casefold().split()),
            " ".join(str(pair["assistant_outcome"]).casefold().split()),
        )
        visible = " ".join(
            format_agent_session_happened(
                distill_agent_session_event(pair, synthesize=False)
            ).casefold().split()
        )
        if signature in seen or visible in seen_visible:
            continue
        seen.add(signature)
        seen_visible.add(visible)
        unique.append(pair)
    return unique


def migrate_pairs(
    pairs: list[dict],
    *,
    dry_run: bool,
    synthesize: bool = False,
    processor=None,
) -> dict:
    """Process a deterministic batch, or report its size without side effects."""
    summary = {
        "dry_run": dry_run,
        "eligible_pairs": len(pairs),
        "processed": 0,
        "written": 0,
        "failed": 0,
    }
    if dry_run:
        return summary
    if processor is None:
        from workflows.hfl.tasks.ingest_agent_sessions import process_agent_session_event

        processor = process_agent_session_event
    results = []
    for payload in pairs:
        try:
            result = processor(payload, synthesize=synthesize)
        except Exception as exc:  # noqa: BLE001
            result = {
                "entries_written": 0,
                "event_id": payload.get("event_id"),
                "error": type(exc).__name__,
            }
        results.append(result)
        summary["processed"] += 1
        summary["written"] += int(result.get("entries_written", 0))
        summary["failed"] += int(bool(result.get("error")))
    summary["results"] = results
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--synthesize", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--since", type=datetime.fromisoformat)
    parser.add_argument("--until", type=datetime.fromisoformat)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    if not args.dry_run:
        from scripts.launch import setup_env

        setup_env()
    all_pairs = collect_session_pairs(
        args.database,
        since=args.since,
        until=args.until,
    )
    stop = args.start + args.limit if args.limit > 0 else None
    pairs = all_pairs[args.start:stop]
    result = migrate_pairs(
        pairs,
        dry_run=args.dry_run,
        synthesize=args.synthesize,
    )
    result.update({
        "total_eligible_pairs": len(all_pairs),
        "batch_start": args.start,
        "batch_limit": args.limit,
        "since": args.since.isoformat() if args.since else None,
        "until": args.until.isoformat() if args.until else None,
    })
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
