"""
WorkspaceOrchestrator — multi-board polling loop.

Wraps N `BoardOrchestrator` instances (one per Trello board) behind a single
process. Boards come from one of two sources:

  1. **Auto-discovery** — `TRELLO_WORKSPACE_ID` is set, `TrelloWorkspace`
     calls `GET /1/organizations/{id}/boards` and the orchestrator picks
     up new boards as they're created in the workspace.
  2. **Static list** — `TRELLO_BOARD_IDS=id1,id2,id3` env var (or the
     legacy single-board `KANBAN_BOARD_ID`) when you don't want auto-discovery.

Routing (profile filter, OS labels) and shared collaborators (TrelloClient,
ProfileRegistry, SecretStore, Mode-A profile-client cache) live here so the
same auth and the same registry are reused across every board.

Re-discovery cadence: when running in auto-discover mode, the workspace
re-fetches its board list every `rediscover_seconds` (default 300s) so newly
created boards get picked up without a process restart.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import sleep, time
from typing import Optional

from agents.projects.orchestrator.board import BoardOrchestrator
from agents.projects.profiles.registry import ProfileRegistry
from agents.projects.security.secret_store import SecretStore
from agents.projects.trello.client import TrelloClient
from agents.projects.trello.workspace import TrelloWorkspace

logger = logging.getLogger(__name__)


class WorkspaceOrchestrator:
    """Polls every board in a Trello workspace and runs agents on eligible cards."""

    def __init__(
        self,
        client: TrelloClient,
        registry: ProfileRegistry,
        api_key: str,
        secret_store: SecretStore,
        os_labels: set[str],
        # Either workspace OR static board_ids must be set.
        workspace: Optional[TrelloWorkspace] = None,
        board_ids: Optional[list[str]] = None,
        # Workspace filter knobs (only used when workspace is set).
        board_name_filter: Optional[str] = None,
        board_name_exclude: Optional[list[str]] = None,
        rediscover_seconds: int = 300,
        # Routing.
        profile_filter: Optional[str] = None,
        # Operations.
        poll_interval: int = 30,
        blocked_poll_interval: int = 300,
        dry_run: bool = False,
        num_agents: int = 1,
        audit_log_path: Optional[Path] = None,
        # Mode A — for building per-profile clients.
        client_factory: Optional[callable] = None,
    ):
        if workspace is None and not board_ids:
            raise ValueError(
                "WorkspaceOrchestrator needs either a TrelloWorkspace "
                "(auto-discovery) or a non-empty board_ids list."
            )

        self.client = client
        self.registry = registry
        self.api_key = api_key
        self._secret_store = secret_store
        self.os_labels = os_labels
        self.workspace = workspace
        self._static_board_ids = board_ids or []
        self.board_name_filter = board_name_filter
        self.board_name_exclude = board_name_exclude
        self.rediscover_seconds = rediscover_seconds
        self.profile_filter = profile_filter
        self.poll_interval = poll_interval
        self.blocked_poll_interval = blocked_poll_interval
        self.dry_run = dry_run
        self.num_agents = max(1, num_agents)
        self._audit_log_path = audit_log_path or Path("logs/projects_audit.jsonl")
        self._client_factory = client_factory

        # Mode A — one cache shared across every board so a profile's per-account
        # client gets reused regardless of which board the card lives on.
        self._profile_clients: dict[str, TrelloClient] = {}

        self._board_orchestrators: dict[str, BoardOrchestrator] = {}
        self._last_discovery: float = 0.0

        logger.info(
            "WorkspaceOrchestrator routing: profile_filter=%s os_labels=%s",
            self.profile_filter or "(any)", sorted(self.os_labels),
        )

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover_boards(self) -> list[str]:
        """Resolve the current set of board IDs to poll.

        Auto-discovery mode (workspace set): re-queries the Trello org each
        call. Static mode (board_ids passed in): returns the configured list.
        """
        if self.workspace is not None:
            try:
                boards = self.workspace.list_boards(
                    name_filter=self.board_name_filter,
                    name_exclude=self.board_name_exclude,
                )
                ids = [b.id for b in boards]
                if not ids:
                    logger.warning(
                        "Workspace %s returned 0 boards (filter=%s exclude=%s) — "
                        "nothing to poll until a board appears or filters change.",
                        self.workspace._workspace_id,
                        self.board_name_filter, self.board_name_exclude,
                    )
                return ids
            except Exception as e:
                logger.error("Workspace discovery failed: %s", e)
                # Fall back to the boards already known so a transient network
                # failure doesn't take the whole orchestrator offline.
                return list(self._board_orchestrators.keys())
        return list(self._static_board_ids)

    def _ensure_board_orchestrators(self, board_ids: list[str]) -> None:
        """Build a BoardOrchestrator for any newly discovered board; drop any
        boards that disappeared (closed or moved out of the workspace).
        """
        current = set(board_ids)
        known = set(self._board_orchestrators.keys())

        for added in current - known:
            self._board_orchestrators[added] = BoardOrchestrator(
                client=self.client,
                registry=self.registry,
                api_key=self.api_key,
                board_id=added,
                secret_store=self._secret_store,
                audit_log_path=self._audit_log_path,
                os_labels=self.os_labels,
                profile_filter=self.profile_filter,
                dry_run=self.dry_run,
                num_agents=self.num_agents,
                profile_clients=self._profile_clients,
                client_factory=self._client_factory,
            )
            logger.info("Added board orchestrator for %s", added)

        for removed in known - current:
            self._board_orchestrators.pop(removed, None)
            logger.info("Dropped board orchestrator for %s (no longer in workspace)", removed)

    # ── Poll across all boards ────────────────────────────────────────────────

    def poll_once(self) -> int:
        """Poll intake on every board this tick. Returns total cards processed."""
        total = 0
        for board_id, orch in self._board_orchestrators.items():
            try:
                resumed = orch.poll_resumes()
                processed = orch.poll_intake()
                if resumed or processed:
                    logger.info(
                        "Board %s: resumed=%d processed=%d", board_id, resumed, processed,
                    )
                total += processed
            except Exception as e:
                logger.error("Unexpected error polling board %s: %s", board_id, e)
        return total

    def poll_blocked(self) -> int:
        total = 0
        for orch in self._board_orchestrators.values():
            try:
                total += orch.poll_blocked()
            except Exception as e:
                logger.error("Blocked-poll error on board %s: %s", orch.board_id, e)
        return total

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the polling loop. Ctrl+C to stop."""
        # Initial discovery + board orchestrator setup.
        self._ensure_board_orchestrators(self.discover_boards())
        self._last_discovery = time()

        logger.info(
            "WorkspaceOrchestrator started | boards=%d | interval=%ds | "
            "blocked_interval=%ds | num_agents=%d | dry_run=%s",
            len(self._board_orchestrators),
            self.poll_interval,
            self.blocked_poll_interval,
            self.num_agents,
            self.dry_run,
        )

        ticks_until_blocked_poll = max(1, self.blocked_poll_interval // max(self.poll_interval, 1))
        tick = 0

        while True:
            try:
                # Re-discover boards if the cadence is up (auto-discovery mode only).
                if (
                    self.workspace is not None
                    and (time() - self._last_discovery) >= self.rediscover_seconds
                ):
                    self._ensure_board_orchestrators(self.discover_boards())
                    self._last_discovery = time()

                processed = self.poll_once()
                if processed:
                    logger.info("Workspace tick: processed %d card(s) total", processed)

                tick += 1
                if tick >= ticks_until_blocked_poll:
                    self.poll_blocked()
                    tick = 0

            except KeyboardInterrupt:
                logger.info("Shutting down workspace orchestrator")
                break
            except Exception as e:
                logger.error("Unexpected workspace tick error: %s", e)
            sleep(self.poll_interval)
