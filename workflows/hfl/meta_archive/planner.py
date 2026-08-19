"""Create resumable, deduplicated thread-week work items from raw exports."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

from workflows.hfl.meta_archive.models import MetaEvent
from workflows.hfl.meta_archive.parsers import (
    parse_facebook_posts, parse_facebook_thread, parse_instagram_html,
)


def content_sha256(content: bytes) -> str:
    """Return the review pin used for manifests and immutable work items."""
    return hashlib.sha256(content).hexdigest()


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def discover_export_roots(roots: Iterable[str], platform: str) -> list[Path]:
    prefix = f"{platform}-"
    found: dict[str, Path] = {}
    for raw in roots:
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            continue
        candidates = [root] if root.name.startswith(prefix) else list(root.glob(f"{prefix}*"))
        for candidate in candidates:
            if candidate.is_dir():
                found[str(candidate).casefold()] = candidate
    return sorted(found.values(), key=lambda path: str(path).casefold())


def _collect(platform: str, exports: list[Path]) -> list[MetaEvent]:
    events: list[MetaEvent] = []
    if platform == "facebook":
        for root in exports:
            for path in root.glob("your_facebook_activity/messages/**/message_*.json"):
                try:
                    events.extend(parse_facebook_thread(path, root))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
            for path in root.glob("your_facebook_activity/**/*post*.json"):
                try:
                    events.extend(parse_facebook_posts(path, root))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
    elif platform == "instagram":
        for root in exports:
            for path in root.glob("your_instagram_activity/messages/**/message_*.html"):
                try:
                    events.extend(parse_instagram_html(path, root, thread_id=path.parent.name))
                except (OSError, ValueError, TypeError):
                    continue
            for path in root.glob("your_instagram_activity/media/*.html"):
                if "post" in path.name.lower() or "stor" in path.name.lower():
                    try:
                        events.extend(parse_instagram_html(path, root, thread_id="authored-content", authored=True))
                    except (OSError, ValueError, TypeError):
                        continue
    else:
        raise ValueError("platform must be facebook or instagram")
    return events


def build_import_plan(*, platform: str, archive_roots: list[str], work_dir: str,
                      max_events: int = 500_000) -> dict:
    exports = discover_export_roots(archive_roots, platform)
    if not exports:
        return {"ok": False, "reason": "no-export-roots", "platform": platform, "items": []}
    unique: dict[str, MetaEvent] = {}
    for event in _collect(platform, exports):
        unique.setdefault(event.event_id, event)
        if len(unique) >= max_events:
            break
    groups: dict[tuple[str, date], list[MetaEvent]] = defaultdict(list)
    for event in unique.values():
        week = event.occurred_at_local.date()
        week = week.fromordinal(week.toordinal() - week.weekday())
        groups[(event.thread_id, week)].append(event)
    root = Path(work_dir).expanduser().resolve() / platform
    root.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    for (thread_id, week), values in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        values.sort(key=lambda event: (event.occurred_at_utc, event.event_id))
        key = f"{platform}-{week.isoformat()}-{values[0].event_id[:16]}"
        path = root / f"{key}.json"
        payload = {"schema_version": 1, "platform": platform, "thread_id": thread_id,
                   "week_start": week.isoformat(), "events": [event.to_dict() for event in values]}
        content = _json_bytes(payload)
        path.write_bytes(content)
        items.append({"key": key, "path": str(path), "thread_id": thread_id,
                      "week_start": week.isoformat(), "event_count": len(values),
                      "sha256": content_sha256(content)})
    manifest = {"ok": True, "schema_version": 1, "platform": platform,
                "exports": [str(path) for path in exports], "events_discovered": len(unique),
                "work_item_count": len(items), "items": items}
    manifest_path = root / "plan.json"
    manifest_content = _json_bytes(manifest)
    manifest_path.write_bytes(manifest_content)
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": content_sha256(manifest_content),
    }


def load_work_item(path: str, *, expected_sha256: str = "",
                   allowed_root: str = "") -> tuple[dict, list[MetaEvent]]:
    resolved = Path(path).expanduser().resolve(strict=True)
    if allowed_root:
        root = Path(allowed_root).expanduser().resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("work item is outside the approved manifest directory")
    content = resolved.read_bytes()
    if expected_sha256:
        expected = expected_sha256.strip().casefold()
        if len(expected) != 64 or content_sha256(content) != expected:
            raise ValueError("work item integrity check failed")
    payload = json.loads(content.decode("utf-8"))
    return payload, [MetaEvent.from_dict(item) for item in payload.get("events") or []]
