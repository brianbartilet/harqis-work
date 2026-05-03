"""
CLI entry + env-based factory for the workspace orchestrator.

No Celery, no Redis, no Docker required. Your dev machine acts as both
orchestrator and worker. Suitable for testing the full agent flow locally.

Run:
    python -m agents.projects.orchestrator.local

Security model (unchanged from the single-board orchestrator):
  - Secrets live in `.env/agents.env` (or `.env/apps.env`); only this process
    reads them.
  - Each agent profile declares which env-var names it needs under
    `secrets.required`; SecretStore scopes per-profile.
  - OutputSanitizer (in BaseKanbanAgent) scrubs everything posted to comments.
  - AuditLogger writes JSONL records for every tool call, permission check,
    and secret access.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from agents.projects.orchestrator.routing import detect_local_os_labels
from agents.projects.orchestrator.workspace import WorkspaceOrchestrator
from agents.projects.profiles.registry import ProfileRegistry
from agents.projects.security.secret_store import SecretStore
from agents.projects.trello.client import TrelloClient
from agents.projects.trello.workspace import TrelloWorkspace

logger = logging.getLogger(__name__)


def from_env(profiles_dir: Optional[Path] = None) -> WorkspaceOrchestrator:
    """Build a WorkspaceOrchestrator from environment variables.

    Required env vars:
        ANTHROPIC_API_KEY
        TRELLO_API_KEY
        TRELLO_API_TOKEN

    Board source — exactly one is required:
        TRELLO_WORKSPACE_ID    Trello org short name or 24-char id
                                → auto-discover every board in the workspace
        TRELLO_BOARD_IDS       comma-separated list of explicit board IDs
                                → polls only those boards (no discovery)
        KANBAN_BOARD_ID        legacy: a single board ID (alias for TRELLO_BOARD_IDS)

    Optional (workspace mode):
        TRELLO_BOARD_NAME_FILTER     substring; only boards whose name contains
                                      this are polled. Case-insensitive.
        TRELLO_BOARD_NAME_EXCLUDE    comma-separated substrings; boards whose
                                      name contains any are skipped.
        TRELLO_REDISCOVER_SECONDS    seconds between workspace re-fetches (default 300).

    Optional (general):
        KANBAN_PROFILES_DIR    path to profiles directory (default: bundled examples)
        KANBAN_POLL_INTERVAL   seconds between polls (default: 30)
        KANBAN_DRY_RUN         set to "1" to skip actual agent execution
        KANBAN_AUDIT_LOG       audit JSONL path (default: logs/projects_audit.jsonl)
        KANBAN_NUM_AGENTS      concurrent agent workers per board (default: 1)
        KANBAN_PROFILE_FILTER  only process cards whose resolved profile id matches
        KANBAN_OS_LABELS       comma-separated `os:*` labels this orchestrator
                                satisfies. Auto-detected from platform.system()
                                when unset (e.g. {os:windows, os:win, os:any}).
    """
    api_key = os.environ["ANTHROPIC_API_KEY"]
    trello_key = os.environ["TRELLO_API_KEY"]
    trello_token = os.environ["TRELLO_API_TOKEN"]

    client = TrelloClient(api_key=trello_key, token=trello_token)

    workspace_id = os.environ.get("TRELLO_WORKSPACE_ID")
    static_board_ids_env = (
        os.environ.get("TRELLO_BOARD_IDS")
        or os.environ.get("KANBAN_BOARD_ID")
        or ""
    )
    static_board_ids = [b.strip() for b in static_board_ids_env.split(",") if b.strip()]

    workspace: Optional[TrelloWorkspace] = None
    if workspace_id:
        workspace = TrelloWorkspace(
            api_key=trello_key,
            token=trello_token,
            workspace_id=workspace_id,
        )
    elif not static_board_ids:
        raise KeyError(
            "Configure either TRELLO_WORKSPACE_ID (auto-discover) or "
            "TRELLO_BOARD_IDS (or legacy KANBAN_BOARD_ID) in the env."
        )

    board_name_filter = os.environ.get("TRELLO_BOARD_NAME_FILTER") or None
    board_name_exclude_env = os.environ.get("TRELLO_BOARD_NAME_EXCLUDE") or ""
    board_name_exclude = [
        s.strip() for s in board_name_exclude_env.split(",") if s.strip()
    ] or None
    rediscover_seconds = int(os.environ.get("TRELLO_REDISCOVER_SECONDS", "300"))

    poll_interval = int(os.environ.get("KANBAN_POLL_INTERVAL", "30"))
    dry_run = os.environ.get("KANBAN_DRY_RUN", "0") == "1"
    num_agents = int(os.environ.get("KANBAN_NUM_AGENTS", "1"))
    audit_log_path = Path(os.environ.get("KANBAN_AUDIT_LOG", "logs/projects_audit.jsonl"))

    if profiles_dir is None:
        profiles_dir_env = os.environ.get("KANBAN_PROFILES_DIR")
        if profiles_dir_env:
            profiles_dir = Path(profiles_dir_env)
        else:
            profiles_dir = Path(__file__).parent.parent / "profiles" / "examples"

    registry = ProfileRegistry.from_dir(profiles_dir)
    logger.info("Loaded %d profile(s) from %s", len(registry), profiles_dir)

    secret_store = SecretStore()

    profile_filter = os.environ.get("KANBAN_PROFILE_FILTER") or None
    os_labels_env = os.environ.get("KANBAN_OS_LABELS")
    os_labels = (
        {x.strip() for x in os_labels_env.split(",") if x.strip()}
        if os_labels_env
        else detect_local_os_labels()
    )

    def _client_factory(*, api_key: str, token: str) -> TrelloClient:
        return TrelloClient(api_key=api_key, token=token)

    return WorkspaceOrchestrator(
        client=client,
        registry=registry,
        api_key=api_key,
        secret_store=secret_store,
        os_labels=os_labels,
        workspace=workspace,
        board_ids=static_board_ids if workspace is None else None,
        board_name_filter=board_name_filter,
        board_name_exclude=board_name_exclude,
        rediscover_seconds=rediscover_seconds,
        profile_filter=profile_filter,
        poll_interval=poll_interval,
        dry_run=dry_run,
        num_agents=num_agents,
        audit_log_path=audit_log_path,
        client_factory=_client_factory,
    )


def _load_dotenv(path: Path) -> None:
    """Minimal dotenv loader — no extra dependency needed."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Trello workspace agent orchestrator (multi-board)"
    )
    parser.add_argument("--profiles-dir", type=Path, help="Path to agent profiles directory")
    parser.add_argument("--poll-interval", type=int, help="Poll interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Don't run agents, just log")
    parser.add_argument(
        "--num-agents", type=int, default=None,
        help="Concurrent agent workers per board (default: 1)",
    )
    parser.add_argument(
        "--profile", type=str, default=None,
        help="Restrict to one profile id (e.g. 'agent:default', 'agent:code'). "
             "Overrides KANBAN_PROFILE_FILTER env var.",
    )
    parser.add_argument(
        "--os", type=str, default=None, dest="os_labels",
        help="Comma-separated os:* labels this orchestrator satisfies "
             "(e.g. 'os:linux,os:gpu'). Auto-detects from host OS when unset. "
             "Overrides KANBAN_OS_LABELS env var.",
    )
    args = parser.parse_args()

    env_file = Path(".env/agents.env")
    if not env_file.exists():
        env_file = Path(".env/apps.env")
    if env_file.exists():
        _load_dotenv(env_file)

    if args.profile:
        os.environ["KANBAN_PROFILE_FILTER"] = args.profile
    if args.os_labels:
        os.environ["KANBAN_OS_LABELS"] = args.os_labels

    orch = from_env(profiles_dir=args.profiles_dir)
    if args.poll_interval:
        orch.poll_interval = args.poll_interval
    if args.dry_run:
        orch.dry_run = True
    if args.num_agents is not None:
        orch.num_agents = max(1, args.num_agents)

    orch.run()
