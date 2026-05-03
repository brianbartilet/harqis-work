"""
Trello workspace (organization) discovery.

A Trello "workspace" is an organization in the API — `GET /1/organizations/{id}/boards`
returns every board the authenticated token can see in that workspace. This is
what powers multi-board orchestration: point the orchestrator at one workspace
ID and it picks up new boards automatically as they're created.

Authentication uses the same TRELLO_API_KEY / TRELLO_API_TOKEN pair as the
client. The workspace ID can be:
  - The org's short name (`harqis-work`)
  - The 24-char organization ID

Filter knobs:
  - `closed=False` skips archived boards by default.
  - `name_filter` and `name_exclude` (substring, case-insensitive) let you scope
    to e.g. "all boards starting with 'agent-'" or skip a personal sandbox board.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.trello.com/1"


@dataclass
class TrelloBoard:
    id: str
    name: str
    short_link: str
    closed: bool
    url: str


class TrelloWorkspace:
    """List + filter the boards in a Trello organization (workspace)."""

    def __init__(
        self,
        api_key: str,
        token: str,
        workspace_id: str,
        timeout: int = 10,
    ):
        if not workspace_id:
            raise ValueError("workspace_id is required (Trello org short name or 24-char id)")
        self._auth = {"key": api_key, "token": token}
        self._timeout = timeout
        self._workspace_id = workspace_id

    def list_boards(
        self,
        include_closed: bool = False,
        name_filter: Optional[str] = None,
        name_exclude: Optional[list[str]] = None,
    ) -> list[TrelloBoard]:
        """Fetch every board in the workspace, with optional filtering.

        Args:
            include_closed: include archived boards (default: False).
            name_filter: only keep boards whose name contains this substring
                (case-insensitive). None = keep all.
            name_exclude: drop boards whose name contains any of these
                substrings (case-insensitive). Useful for skipping a personal
                sandbox board that lives in the same workspace.

        Raises requests.HTTPError on auth/permission failure — the orchestrator
        should treat that as fatal at startup, not silently degrade.
        """
        url = f"{_BASE}/organizations/{self._workspace_id}/boards"
        params = {
            **self._auth,
            "fields": "id,name,shortLink,closed,url",
            "filter": "all" if include_closed else "open",
        }
        r = requests.get(url, params=params, timeout=self._timeout)
        r.raise_for_status()

        boards = [
            TrelloBoard(
                id=b["id"],
                name=b["name"],
                short_link=b.get("shortLink", ""),
                closed=b.get("closed", False),
                url=b.get("url", ""),
            )
            for b in r.json()
        ]

        if name_filter:
            needle = name_filter.lower()
            boards = [b for b in boards if needle in b.name.lower()]
        if name_exclude:
            excludes = [s.lower() for s in name_exclude]
            boards = [
                b for b in boards
                if not any(x in b.name.lower() for x in excludes)
            ]

        logger.info(
            "Discovered %d board(s) in workspace %s (filter=%s exclude=%s)",
            len(boards), self._workspace_id, name_filter, name_exclude,
        )
        return boards
