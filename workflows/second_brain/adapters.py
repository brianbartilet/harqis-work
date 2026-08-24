"""Deterministic client renderers; redaction happens before text rendering."""

from __future__ import annotations

from typing import Any, Iterable


def client_items(snapshot: dict[str, Any], *, client: str) -> list[dict[str, Any]]:
    items = []
    for raw in snapshot.get("items") or []:
        if client not in (raw.get("allowed_clients") or []):
            continue
        item = dict(raw)
        if client != "web":
            item["details"] = ""
            item["source_refs"] = []
            if item.get("sensitivity") not in {"public", "internal"}:
                item["summary"] = "Sensitive update available in the authenticated web feed."
                item["links"] = {}
        items.append(item)
    return items


def render_text(items: Iterable[dict[str, Any]], *, title: str = "SECOND BRAIN", limit: int = 10) -> str:
    selected = list(items)[:max(1, min(25, int(limit)))]
    if not selected:
        return f"{title}\n\nNo fresh advisory items."
    lines = [title, ""]
    for item in selected:
        category = str(item.get("category") or "context").upper()
        lines.append(f"[{category}] {str(item.get('title') or '')[:180]}")
        summary = str(item.get("summary") or "").strip()
        if summary:
            lines.append(f"  {summary[:240]}")
    return "\n".join(lines)
