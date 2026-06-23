"""
workflows/knowledge/watchlists — loader for watchlists.yaml.

A watchlist bundles the keywords, semantic prompt, and service vocabulary for a
standing interest. `topic_scan` consumes these; the cross-linker pulls the
`services` list as its entity vocabulary.

Override the file with HARQIS_KNOWLEDGE_WATCHLISTS (absolute path) to keep a
private, org-specific set out of this public repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parent / "watchlists.yaml"


@dataclass
class Watchlist:
    id: str
    title: str
    keywords: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    semantic_prompt: str = ""
    cadence: str = "manual"

    @property
    def query_text(self) -> str:
        """A single retrieval query combining the semantic prompt + keywords."""
        kw = ", ".join(self.keywords)
        return (self.semantic_prompt.strip() + ("\nKeywords: " + kw if kw else "")).strip()


def _path() -> Path:
    override = os.environ.get("HARQIS_KNOWLEDGE_WATCHLISTS", "").strip()
    return Path(override) if override else _DEFAULT_PATH


def load_watchlists(path: Path | None = None) -> list[Watchlist]:
    """Parse the watchlist file into Watchlist objects. Returns [] if missing."""
    p = path or _path()
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: list[Watchlist] = []
    for raw in data.get("watchlists", []) or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        out.append(Watchlist(
            id=str(raw["id"]),
            title=str(raw.get("title", raw["id"])),
            keywords=list(raw.get("keywords", []) or []),
            services=list(raw.get("services", []) or []),
            sources=list(raw.get("sources", []) or []),
            semantic_prompt=str(raw.get("semantic_prompt", "") or ""),
            cadence=str(raw.get("cadence", "manual")),
        ))
    return out


def get_watchlist(watchlist_id: str, path: Path | None = None) -> Watchlist | None:
    for w in load_watchlists(path):
        if w.id == watchlist_id:
            return w
    return None


def all_services(path: Path | None = None) -> list[str]:
    """Union of every watchlist's `services` — the default entity vocabulary."""
    seen: set[str] = set()
    out: list[str] = []
    for w in load_watchlists(path):
        for s in w.services:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out
