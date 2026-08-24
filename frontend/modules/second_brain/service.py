"""Presentation policy and canonical Second Brain store access."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from config import get_settings
from services.markdown import render_markdown


@lru_cache(maxsize=1)
def get_second_brain_store():
    from workflows.second_brain.store import SecondBrainStore

    return SecondBrainStore(Path(get_settings().second_brain_store_path).expanduser().resolve())


def reset_second_brain_store() -> None:
    get_second_brain_store.cache_clear()


def _redact(item: dict[str, Any], *, client: str) -> dict[str, Any]:
    rendered = dict(item)
    if client != "web":
        rendered["details"] = ""
        rendered["source_refs"] = []
        if rendered.get("sensitivity") not in {"public", "internal"}:
            rendered["summary"] = "Sensitive update available in the authenticated web feed."
            rendered["links"] = {}
    return rendered


def snapshot(*, client: str = "web", limit: int = 100) -> dict[str, Any]:
    store = get_second_brain_store()
    config = store.get_config()
    clients = config.get("clients") or {}
    if client not in {"web", "telegram", "rainmeter", "cli"}:
        raise ValueError("unsupported client")
    if client != "web" and not clients.get(client, False):
        raise PermissionError(f"{client} client is disabled")
    decision = store.latest_decision()
    result = store.feed_snapshot(
        client=client,
        limit=limit,
        modes=(),
    )
    active_modes = set((decision or {}).get("effective_modes") or ())
    known_modes = {mode["mode_id"] for mode in config.get("modes") or []}
    result["items"] = [
        {**item, "archived_source": item.get("category") not in known_modes}
        for item in result["items"]
        if not active_modes or item.get("category") in active_modes or item.get("category") not in known_modes
    ][:limit]
    result["items"] = [_redact(item, client=client) for item in result["items"]]
    if client == "web":
        for item in result["items"]:
            item["details_html"] = render_markdown(item.get("details") or item.get("summary") or "")
    result["decision"] = decision
    result["override"] = store.active_override()
    result["config"] = config
    result["modes"] = store.list_modes()
    result["mode_map"] = {mode["mode_id"]: mode for mode in result["modes"]}
    result["automatic_feed"] = result["override"] is None
    result["chat"] = [
        {**message, "content_html": render_markdown(message["content"])}
        for message in store.recent_chat(limit=40)
    ]
    from workflows.second_brain.registry import operation_catalog
    from apps.google_apps.references.constants import ScheduleCategory

    result["operations"] = operation_catalog()
    result["calendar_categories"] = [value.value for value in ScheduleCategory if value.name not in {"PINNED", "DEACTIVATED"}]
    return result


def changes_after(cursor: int, *, client: str = "web") -> list[dict[str, Any]]:
    store = get_second_brain_store()
    return [
        {**change, "item": _redact(change["item"], client=client)}
        for change in store.changes_after(cursor, client=client)
    ]
