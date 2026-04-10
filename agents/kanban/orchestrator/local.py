"""
LocalOrchestrator — single-process polling orchestrator for local development.

No Celery, no Redis, no Docker required. Your dev machine acts as both
orchestrator and worker. Suitable for testing the full agent flow locally.

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
from pathlib import Path
from time import sleep
from typing import Optional

from agents.kanban.agent.base import BaseKanbanAgent
from agents.kanban.factory import create_provider
from agents.kanban.interface import KanbanCard, KanbanProvider
from agents.kanban.profiles.registry import ProfileRegistry
from agents.kanban.profiles.schema import AgentProfile

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
        poll_interval: int = 30,
        dry_run: bool = False,
    ):
        self.provider = provider
        self.registry = registry
        self.api_key = api_key
        self.board_id = board_id
        self.poll_interval = poll_interval
        self.dry_run = dry_run

    # ── Single card processing ────────────────────────────────────────────────

    def process_card(self, card: KanbanCard) -> Optional[str]:
        """
        Claim a card, run its agent, post result, move to Review/Done.
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

        # Step 1: Claim
        try:
            self.provider.move_card(card.id, "Claimed")
            self.provider.add_comment(card.id, f"claimed-by: {profile.name}")
        except Exception as e:
            logger.error("Failed to claim card %s: %s", card.id, e)
            return None

        # Step 2: Mark in progress
        try:
            self.provider.move_card(card.id, "In Progress")
        except Exception as e:
            logger.warning("Could not move to 'In Progress': %s", e)

        # Step 3: Run agent
        try:
            agent = BaseKanbanAgent(
                profile=profile,
                card=card,
                provider=self.provider,
                api_key=self.api_key,
            )
            result = agent.run()
        except Exception as e:
            self._handle_error(card, profile, e)
            return None

        # Step 4: Post result
        try:
            self.provider.add_comment(card.id, f"## Result\n\n{result}")
            destination = "Done" if profile.lifecycle.auto_approve else "Review"
            self.provider.move_card(card.id, destination)
            logger.info("Card %s → %s", card.id, destination)
        except Exception as e:
            logger.error("Failed to post result for card %s: %s", card.id, e)

        return result

    def _handle_error(self, card: KanbanCard, profile: AgentProfile, exc: Exception) -> None:
        tb = traceback.format_exc()
        logger.error("Agent error on card %s:\n%s", card.id, tb)
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

        count = 0
        for card in cards:
            if self.registry.resolve_for_card(card):
                result = self.process_card(card)
                if result is not None:
                    count += 1
        return count

    def run(self) -> None:
        """Start the polling loop. Ctrl+C to stop."""
        logger.info(
            "LocalOrchestrator started | board=%s | interval=%ds | dry_run=%s",
            self.board_id,
            self.poll_interval,
            self.dry_run,
        )
        while True:
            try:
                n = self.poll_once()
                if n:
                    logger.info("Processed %d card(s)", n)
                else:
                    logger.debug("Nothing to do")
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
        JIRA_SERVER
        JIRA_EMAIL
        JIRA_API_TOKEN

    Optional:
        KANBAN_PROFILES_DIR   path to profiles directory (default: agents/kanban/profiles/examples)
        KANBAN_POLL_INTERVAL  seconds between polls (default: 30)
        KANBAN_DRY_RUN        set to "1" to skip actual agent execution
    """
    provider_type = os.environ.get("KANBAN_PROVIDER", "trello").lower()

    if provider_type == "trello":
        provider_config = {
            "provider": "trello",
            "api_key": os.environ["TRELLO_API_KEY"],
            "token": os.environ["TRELLO_API_TOKEN"],
        }
    elif provider_type == "jira":
        provider_config = {
            "provider": "jira",
            "server": os.environ["JIRA_SERVER"],
            "email": os.environ["JIRA_EMAIL"],
            "api_token": os.environ["JIRA_API_TOKEN"],
        }
    else:
        raise ValueError(f"Unknown KANBAN_PROVIDER: {provider_type}")

    provider = create_provider(provider_config)

    board_id = os.environ["KANBAN_BOARD_ID"]
    api_key = os.environ["ANTHROPIC_API_KEY"]
    poll_interval = int(os.environ.get("KANBAN_POLL_INTERVAL", "30"))
    dry_run = os.environ.get("KANBAN_DRY_RUN", "0") == "1"

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

    return LocalOrchestrator(
        provider=provider,
        registry=registry,
        api_key=api_key,
        board_id=board_id,
        poll_interval=poll_interval,
        dry_run=dry_run,
    )


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
    args = parser.parse_args()

    # Load .env file if present
    env_file = Path(".env/agents.env")
    if not env_file.exists():
        env_file = Path(".env/apps.env")
    if env_file.exists():
        from agents.kanban.orchestrator.local import _load_dotenv
        _load_dotenv(env_file)

    orch = from_env(profiles_dir=args.profiles_dir)
    if args.poll_interval:
        orch.poll_interval = args.poll_interval
    if args.dry_run:
        orch.dry_run = True

    orch.run()


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
