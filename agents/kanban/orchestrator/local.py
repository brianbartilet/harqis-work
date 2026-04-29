"""
LocalOrchestrator — single-process polling orchestrator for local development.

No Celery, no Redis, no Docker required. Your dev machine acts as both
orchestrator and worker. Suitable for testing the full agent flow locally.

Security model:
  - All secrets live in one env file (e.g. .env/agents.env) — only the
    orchestrator process reads it.
  - Each agent profile declares which env-var names it needs under
    `secrets.required`.
  - `SecretStore` extracts only those vars and passes a scoped dict to
    each agent — the agent never sees the full env file.
  - `OutputSanitizer` (inside BaseKanbanAgent) scrubs all output before
    it is posted to Kanban comments or returned to callers.
  - `AuditLogger` writes a JSONL record for every tool call, permission
    check, and secret access to logs/kanban_audit.jsonl.

Run:
    python -m agents.kanban.orchestrator.local

Or from code:
    from agents.kanban.orchestrator.local import LocalOrchestrator, from_env
    orchestrator = from_env()
    orchestrator.run()
"""

from __future__ import annotations

import logging
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import sleep
from typing import Optional

from agents.kanban.agent.base import BaseKanbanAgent
from agents.kanban.dependencies.detector import DependencyDetector
from agents.kanban.factory import create_provider
from agents.kanban.interface import KanbanCard, KanbanProvider
from agents.kanban.orchestrator.blocked_handler import BlockedCardHandler
from agents.kanban.profiles.registry import ProfileRegistry
from agents.kanban.profiles.schema import AgentProfile
from agents.kanban.security.audit import AuditLogger, NullAuditLogger
from agents.kanban.security.secret_store import SecretStore

logger = logging.getLogger(__name__)


class LocalOrchestrator:
    """
    Single-process orchestrator.

    Polls the Kanban board for cards in 'Backlog', matches them to agent
    profiles, and runs agents synchronously (one at a time in the POC).
    """

    def __init__(
        self,
        provider: KanbanProvider,
        registry: ProfileRegistry,
        api_key: str,
        board_id: str,
        secret_store: Optional[SecretStore] = None,
        poll_interval: int = 30,
        dry_run: bool = False,
        audit_log_path: Optional[Path] = None,
        num_agents: int = 1,
    ):
        self.provider = provider
        self.registry = registry
        self.api_key = api_key
        self.board_id = board_id
        self._secret_store = secret_store or SecretStore()
        self.poll_interval = poll_interval
        self.dry_run = dry_run
        self._audit_log_path = audit_log_path or Path("logs/kanban_audit.jsonl")
        self.num_agents = max(1, num_agents)
        self._dep_detector = DependencyDetector()
        self._blocked_handler = BlockedCardHandler(provider, board_id)
        self._blocked_poll_countdown = 0

    # ── Single card processing ────────────────────────────────────────────────

    def process_card(self, card: KanbanCard) -> Optional[str]:
        """
        Claim a card, run its agent, post result, move to Done.
        Returns the result text, or None on error.
        """
        profile = self.registry.resolve_for_card(card)
        if not profile:
            logger.debug("No profile for card %s (labels=%s)", card.id, card.labels)
            return None

        logger.info(
            "Processing card '%s' | id=%s | profile=%s",
            card.title, card.id, profile.id,
        )

        if self.dry_run:
            logger.info("[DRY RUN] Would run %s on card %s", profile.id, card.id)
            return "[dry-run]"

        # Dependency check — block if hard-stop deps are unmet
        if profile.lifecycle.detect_dependencies and profile.lifecycle.block_on_missing_secrets:
            dep_result = self._dep_detector.detect(card)
            if dep_result.has_blocking:
                logger.warning(
                    "Card '%s' has blocking dependencies — moving to Blocked", card.title
                )
                try:
                    summary = dep_result.blocker_summary()
                    self.provider.add_comment(
                        card.id,
                        f"## Agent: Blocked\n\n"
                        f"Cannot start — the following dependencies must be resolved by the maintainer:\n\n"
                        f"{summary}\n\n"
                        f"Once resolved, the card will be automatically re-queued.",
                    )
                    self.provider.move_card(card.id, "Blocked")
                except Exception as e:
                    logger.error("Failed to block card %s: %s", card.id, e)
                return None

        # Scope secrets to only what this profile declared it needs
        try:
            scoped = self._secret_store.scoped_for_profile(profile)
            # Always ensure ANTHROPIC_API_KEY is present even if not declared
            if "ANTHROPIC_API_KEY" not in scoped:
                scoped["ANTHROPIC_API_KEY"] = self.api_key
        except KeyError as e:
            logger.error("Missing required secret for profile %s: %s", profile.id, e)
            try:
                self.provider.add_comment(
                    card.id,
                    f"## Agent Error\n\nCould not start: missing required secret {e}",
                )
                self.provider.move_card(card.id, "Failed")
            except Exception:
                pass
            return None

        audit = AuditLogger(
            agent_id=profile.id,
            card_id=card.id,
            log_path=self._audit_log_path,
        )
        audit.secret_access(profile.id, list(scoped.keys()))

        # Step 1: Claim
        try:
            self.provider.move_card(card.id, "Pending")
            self.provider.add_comment(card.id, f"claimed-by: {profile.name}")
            audit.card_lifecycle("Backlog", "Pending")
        except Exception as e:
            logger.error("Failed to claim card %s: %s", card.id, e)
            return None

        # Step 2: Mark in progress
        try:
            self.provider.move_card(card.id, "In Progress")
            audit.card_lifecycle("Pending", "In Progress")
        except Exception as e:
            logger.warning("Could not move to 'In Progress': %s", e)

        # Step 3: Run agent
        try:
            agent = BaseKanbanAgent(
                profile=profile,
                card=card,
                provider=self.provider,
                api_key=self.api_key,
                scoped_secrets=scoped,
                audit=audit,
            )
            result = agent.run()
        except Exception as e:
            self._handle_error(card, profile, e, audit)
            return None

        # Step 4: Post result (already sanitized by agent)
        try:
            self.provider.add_comment(card.id, f"## Result\n\n{result}")
            destination = "Done"
            self.provider.move_card(card.id, destination)
            audit.card_lifecycle("In Progress", destination)
            logger.info("Card %s → %s", card.id, destination)
        except Exception as e:
            logger.error("Failed to post result for card %s: %s", card.id, e)

        return result

    def _handle_error(
        self,
        card: KanbanCard,
        profile: AgentProfile,
        exc: Exception,
        audit: Optional[AuditLogger] = None,
    ) -> None:
        tb = traceback.format_exc()
        logger.error("Agent error on card %s:\n%s", card.id, tb)
        if audit:
            audit.agent_finish(success=False, iterations=0, detail=str(exc))
        try:
            self.provider.add_comment(
                card.id,
                f"## Agent Error\n\n```\n{tb}\n```",
            )
            self.provider.move_card(card.id, "Failed")
        except Exception as post_err:
            logger.error("Could not post error comment: %s", post_err)

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def poll_once(self) -> int:
        """Poll backlog once. Returns number of cards processed."""
        try:
            cards = self.provider.get_cards(self.board_id, "Backlog")
        except Exception as e:
            logger.error("Failed to fetch Backlog: %s", e)
            return 0

        matched = []
        for card in cards:
            profile = self.registry.resolve_for_card(card)
            if profile:
                matched.append(card)
            else:
                logger.info(
                    "No profile match for card '%s' (labels=%s) — skipping",
                    card.title, card.labels,
                )

        if not matched:
            return 0

        if self.num_agents == 1:
            count = 0
            for card in matched:
                result = self.process_card(card)
                if result is not None:
                    count += 1
            return count

        logger.info(
            "Dispatching %d card(s) across %d agent worker(s)",
            len(matched), self.num_agents,
        )
        count = 0
        with ThreadPoolExecutor(max_workers=self.num_agents) as pool:
            futures = {pool.submit(self.process_card, card): card for card in matched}
            for future in as_completed(futures):
                card = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        count += 1
                except Exception as e:
                    logger.error("Unhandled error processing card %s: %s", card.id, e)
        return count

    def poll_blocked(self) -> int:
        """
        Check the Blocked column for cards whose dependencies are now resolved.
        Returns the number of cards re-queued to Backlog.
        """
        n = self._blocked_handler.poll_once()
        if n:
            logger.info("Re-queued %d previously blocked card(s)", n)
        return n

    def run(self) -> None:
        """
        Start the polling loop. Ctrl+C to stop.

        Every poll_interval seconds the Backlog is checked. Blocked cards are
        rechecked on a separate cadence (blocked_poll_interval_seconds from the
        first profile loaded, defaulting to 300 s).
        """
        # Derive blocked poll interval from the registry's first profile, if any
        blocked_interval = 300
        try:
            first_profile = next(iter(self.registry))
            blocked_interval = first_profile.lifecycle.blocked_poll_interval_seconds
        except (StopIteration, AttributeError):
            pass

        logger.info(
            "LocalOrchestrator started | board=%s | interval=%ds | blocked_interval=%ds | num_agents=%d | dry_run=%s",
            self.board_id,
            self.poll_interval,
            blocked_interval,
            self.num_agents,
            self.dry_run,
        )

        ticks_until_blocked_poll = blocked_interval // max(self.poll_interval, 1)
        tick = 0

        while True:
            try:
                n = self.poll_once()
                if n:
                    logger.info("Processed %d card(s)", n)
                else:
                    logger.debug("Nothing to do")

                tick += 1
                if tick >= ticks_until_blocked_poll:
                    self.poll_blocked()
                    tick = 0

            except KeyboardInterrupt:
                logger.info("Shutting down orchestrator")
                break
            except Exception as e:
                logger.error("Unexpected poll error: %s", e)
            sleep(self.poll_interval)


# ── Factory from environment variables ────────────────────────────────────────

def from_env(profiles_dir: Optional[Path] = None) -> LocalOrchestrator:
    """
    Build a LocalOrchestrator from environment variables.

    Required env vars:
        KANBAN_PROVIDER       trello or jira (default: trello)
        KANBAN_BOARD_ID       Trello board ID or Jira project key
        ANTHROPIC_API_KEY     Claude API key

    Trello-specific:
        TRELLO_API_KEY
        TRELLO_API_TOKEN

    Jira-specific:
        JIRA_DOMAIN     e.g. yourcompany.atlassian.net (canonical name in .env/apps.env;
                        JIRA_SERVER also accepted as a legacy fallback)
        JIRA_EMAIL
        JIRA_API_TOKEN

    Optional:
        KANBAN_PROFILES_DIR   path to profiles directory (default: agents/kanban/profiles/examples)
        KANBAN_POLL_INTERVAL  seconds between polls (default: 60)
        KANBAN_DRY_RUN        set to "1" to skip actual agent execution
        KANBAN_AUDIT_LOG      path to audit JSONL file (default: logs/kanban_audit.jsonl)
        KANBAN_NUM_AGENTS     number of concurrent agent workers on this host (default: 1)
    """
    provider_type = os.environ.get("KANBAN_PROVIDER", "trello").lower()

    if provider_type == "trello":
        provider_config = {
            "provider": "trello",
            "api_key": os.environ["TRELLO_API_KEY"],
            "token": os.environ["TRELLO_API_TOKEN"],
        }
    elif provider_type == "jira":
        # Canonical name is JIRA_DOMAIN (matches apps_config.yaml); JIRA_SERVER kept as legacy.
        jira_server = os.environ.get("JIRA_DOMAIN") or os.environ.get("JIRA_SERVER")
        if not jira_server:
            raise KeyError("JIRA_DOMAIN (or legacy JIRA_SERVER) must be set for KANBAN_PROVIDER=jira")
        # Accept either bare host (yourcompany.atlassian.net) or full URL.
        if not jira_server.startswith(("http://", "https://")):
            jira_server = f"https://{jira_server}"
        provider_config = {
            "provider": "jira",
            "server": jira_server,
            "email": os.environ["JIRA_EMAIL"],
            "api_token": os.environ["JIRA_API_TOKEN"],
        }
    else:
        raise ValueError(f"Unknown KANBAN_PROVIDER: {provider_type}")

    provider = create_provider(provider_config)

    board_id = os.environ["KANBAN_BOARD_ID"]
    api_key = os.environ["ANTHROPIC_API_KEY"]
    poll_interval = int(os.environ.get("KANBAN_POLL_INTERVAL", "60"))
    dry_run = os.environ.get("KANBAN_DRY_RUN", "0") == "1"
    num_agents = int(os.environ.get("KANBAN_NUM_AGENTS", "1"))

    audit_log_path = Path(os.environ.get("KANBAN_AUDIT_LOG", "logs/kanban_audit.jsonl"))

    # Profiles directory
    if profiles_dir is None:
        profiles_dir_env = os.environ.get("KANBAN_PROFILES_DIR")
        if profiles_dir_env:
            profiles_dir = Path(profiles_dir_env)
        else:
            # Default: examples bundled with the module
            profiles_dir = Path(__file__).parent.parent / "profiles" / "examples"

    registry = ProfileRegistry.from_dir(profiles_dir)
    logger.info("Loaded %d profile(s) from %s", len(registry), profiles_dir)

    # SecretStore reads the full env once; agents receive only scoped subsets
    secret_store = SecretStore()

    return LocalOrchestrator(
        provider=provider,
        registry=registry,
        api_key=api_key,
        board_id=board_id,
        secret_store=secret_store,
        poll_interval=poll_interval,
        dry_run=dry_run,
        audit_log_path=audit_log_path,
        num_agents=num_agents,
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

    parser = argparse.ArgumentParser(description="Kanban agent local orchestrator")
    parser.add_argument("--profiles-dir", type=Path, help="Path to agent profiles directory")
    parser.add_argument("--poll-interval", type=int, help="Poll interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Don't run agents, just log")
    parser.add_argument(
        "--num-agents", type=int, default=None,
        help="Number of concurrent agent workers on this host (default: 1)",
    )
    args = parser.parse_args()

    # Load .env file if present
    env_file = Path(".env/agents.env")
    if not env_file.exists():
        env_file = Path(".env/apps.env")
    if env_file.exists():
        _load_dotenv(env_file)

    orch = from_env(profiles_dir=args.profiles_dir)
    if args.poll_interval:
        orch.poll_interval = args.poll_interval
    if args.dry_run:
        orch.dry_run = True
    if args.num_agents is not None:
        orch.num_agents = max(1, args.num_agents)

    orch.run()
