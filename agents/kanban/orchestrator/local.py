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
import platform
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import sleep
from typing import Optional

from agents.kanban.agent.base import AgentExecutionError, BaseKanbanAgent
from agents.kanban.agent.persona import sign_comment
from agents.kanban.dependencies.detector import DependencyDetector
from agents.kanban.factory import create_provider
from agents.kanban.interface import KanbanCard, KanbanProvider
from agents.kanban.orchestrator.blocked_handler import BlockedCardHandler
from agents.kanban.profiles.registry import ProfileRegistry
from agents.kanban.profiles.schema import AgentProfile, ProviderCredentialsConfig
from agents.kanban.security.audit import AuditLogger, NullAuditLogger
from agents.kanban.security.secret_store import SecretStore

logger = logging.getLogger(__name__)


def detect_local_hw_labels() -> set[str]:
    """Return the set of `hw:*` labels this machine satisfies.

    Auto-detected from `platform.system()`. macOS gets both `hw:darwin` and
    `hw:macos` so card authors can use either spelling. Linux and Windows are
    one each.
    """
    sysname = platform.system().lower()
    if sysname == "darwin":
        return {"hw:darwin", "hw:macos"}
    if sysname == "linux":
        return {"hw:linux"}
    if sysname == "windows":
        return {"hw:windows"}
    return {f"hw:{sysname}"}


def card_hw_required(card: KanbanCard) -> set[str]:
    """Return the set of `hw:*` labels declared on a card."""
    return {lbl for lbl in (card.labels or []) if lbl.startswith("hw:")}


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
        provider_config: Optional[dict] = None,
        profile_filter: Optional[str] = None,
        hw_labels: Optional[set[str]] = None,
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
        # Mode A — per-profile provider cache.
        self._provider_config = provider_config or {}
        self._profile_providers: dict[str, KanbanProvider] = {}
        # Routing — per-orchestrator filters that decide which cards this
        # orchestrator is willing to claim.
        # - profile_filter: only handle cards whose resolved profile id matches.
        #   None means "any profile" (legacy single-orchestrator behaviour).
        # - hw_labels: the `hw:*` labels this orchestrator's machine satisfies.
        #   None auto-detects from the host OS. Cards with no hw:* label match
        #   any orchestrator; cards with hw:* labels only match orchestrators
        #   whose hw_labels include at least one of them.
        self.profile_filter: Optional[str] = profile_filter
        self.hw_labels: set[str] = hw_labels if hw_labels is not None else detect_local_hw_labels()
        logger.info(
            "Orchestrator routing: profile_filter=%s hw_labels=%s",
            self.profile_filter or "(any)", sorted(self.hw_labels),
        )

    # ── Routing ───────────────────────────────────────────────────────────────

    def _card_is_for_me(
        self, card: KanbanCard, profile: Optional[AgentProfile]
    ) -> tuple[bool, str]:
        """Return (eligible, reason) for whether this orchestrator should
        process this card. `reason` is a one-line string for logging when
        eligible=False; empty when eligible.
        """
        # Profile filter: card's resolved profile must match.
        if self.profile_filter:
            if profile is None or profile.id != self.profile_filter:
                resolved = profile.id if profile else "(none)"
                return False, f"profile mismatch (card={resolved}, filter={self.profile_filter})"

        # Hardware filter: any hw:* label on the card must intersect this
        # orchestrator's hw_labels.
        required_hw = card_hw_required(card)
        if required_hw and not (required_hw & self.hw_labels):
            return False, f"hw mismatch (card needs {sorted(required_hw)}, this host satisfies {sorted(self.hw_labels)})"

        return True, ""

    # ── Per-profile provider (Mode A) ─────────────────────────────────────────

    def provider_for_profile(self, profile: AgentProfile) -> KanbanProvider:
        """Return the KanbanProvider for this profile.

        Mode A: if the profile has `provider_credentials` set AND the named env
        vars are populated, build (and cache) a per-profile provider that
        authenticates as that agent's own Trello/Jira account. All actions
        (comments, moves, claims) then attribute to that account natively.

        Mode B: otherwise, return the global provider — the orchestrator will
        sign comments with the persona block instead.
        """
        creds = profile.provider_credentials
        if not creds.is_set() or not self._provider_config:
            return self.provider

        cached = self._profile_providers.get(profile.id)
        if cached is not None:
            return cached

        kind = self._provider_config.get("provider", "trello").lower()
        config = dict(self._provider_config)

        if kind == "trello":
            api_key = os.environ.get(creds.trello_api_key_env) if creds.trello_api_key_env else None
            token = os.environ.get(creds.trello_api_token_env) if creds.trello_api_token_env else None
            if not api_key or not token:
                logger.info(
                    "Profile %s declares Trello provider_credentials but env vars "
                    "(%s / %s) are not set — falling back to global provider (Mode B).",
                    profile.id, creds.trello_api_key_env, creds.trello_api_token_env,
                )
                return self.provider
            config["api_key"] = api_key
            config["token"] = token
        elif kind == "jira":
            email = os.environ.get(creds.jira_email_env) if creds.jira_email_env else None
            api_token = os.environ.get(creds.jira_api_token_env) if creds.jira_api_token_env else None
            if not email or not api_token:
                logger.info(
                    "Profile %s declares Jira provider_credentials but env vars "
                    "(%s / %s) are not set — falling back to global provider (Mode B).",
                    profile.id, creds.jira_email_env, creds.jira_api_token_env,
                )
                return self.provider
            config["email"] = email
            config["api_token"] = api_token

        per_profile = create_provider(config)
        self._profile_providers[profile.id] = per_profile
        logger.info("Mode A active for profile %s — using dedicated %s account", profile.id, kind)
        return per_profile

    def _post_comment(
        self, card_id: str, body: str, profile: Optional[AgentProfile] = None
    ) -> None:
        """Post a comment using the right provider, with persona signature applied
        (Mode B). When the profile is None or the per-profile provider is being used
        (Mode A), the signature is skipped — the underlying account already attributes
        the comment correctly.
        """
        if profile is not None:
            target = self.provider_for_profile(profile)
            using_mode_a = target is not self.provider
            if not using_mode_a:
                body = sign_comment(profile, body)
        else:
            target = self.provider
        target.add_comment(card_id, body)

    def _provider_move(
        self, card_id: str, column: str, profile: Optional[AgentProfile] = None
    ) -> None:
        """Move a card via the right provider (per-profile for Mode A)."""
        target = self.provider_for_profile(profile) if profile else self.provider
        target.move_card(card_id, column)

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

        # Routing — apply profile + hw filters BEFORE making any provider calls.
        eligible, reason = self._card_is_for_me(card, profile)
        if not eligible:
            logger.debug("Skipping card %s — %s", card.id, reason)
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
                    self._post_comment(
                        card.id,
                        f"## Agent: Blocked\n\n"
                        f"Cannot start — the following dependencies must be resolved by the maintainer:\n\n"
                        f"{summary}\n\n"
                        f"Once resolved, the card will be automatically re-queued.",
                        profile,
                    )
                    self._provider_move(card.id, "Blocked", profile)
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
                self._post_comment(
                    card.id,
                    f"## Agent Error\n\nCould not start: missing required secret {e}",
                    profile,
                )
                self._provider_move(card.id, "Failed", profile)
            except Exception:
                pass
            return None

        audit = AuditLogger(
            agent_id=profile.id,
            card_id=card.id,
            log_path=self._audit_log_path,
        )
        audit.secret_access(profile.id, list(scoped.keys()))

        # Resolve the per-profile provider once (cached) — this is what claims,
        # comments, and moves use so the right Trello/Jira account gets attribution.
        agent_provider = self.provider_for_profile(profile)

        # Step 1: Claim
        try:
            self._provider_move(card.id, "Pending", profile)
            self._post_comment(card.id, f"claimed-by: {profile.name}", profile)
            audit.card_lifecycle("Backlog", "Pending")
        except Exception as e:
            logger.error("Failed to claim card %s: %s", card.id, e)
            return None

        # Step 2: Mark in progress
        try:
            self._provider_move(card.id, "In Progress", profile)
            audit.card_lifecycle("Pending", "In Progress")
        except Exception as e:
            logger.warning("Could not move to 'In Progress': %s", e)

        # Step 3: Run agent
        try:
            agent = BaseKanbanAgent(
                profile=profile,
                card=card,
                provider=agent_provider,
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
            self._post_comment(card.id, f"## Result\n\n{result}", profile)
            destination = "Done"
            self._provider_move(card.id, destination, profile)
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
        if isinstance(exc, AgentExecutionError):
            # Clean, expected failure from the agent itself (API limit, rate limit,
            # bad request, etc). Don't dump a Python traceback into the card —
            # surface the kind + message clearly.
            heading = {
                "api_usage_limit": "Agent Failed — Anthropic usage limit reached",
                "api_rate_limit":  "Agent Failed — Anthropic rate limit (transient)",
                "api_error":       "Agent Failed — Anthropic API error",
            }.get(exc.kind, f"Agent Failed — {exc.kind}")
            comment = f"## {heading}\n\n```\n{exc}\n```"
            logger.error("Agent failed on card %s (%s): %s", card.id, exc.kind, exc)
        else:
            tb = traceback.format_exc()
            comment = f"## Agent Error\n\n```\n{tb}\n```"
            logger.error("Agent error on card %s:\n%s", card.id, tb)
        if audit:
            audit.agent_finish(success=False, iterations=0, detail=str(exc))
        try:
            self._post_comment(card.id, comment, profile)
            self._provider_move(card.id, "Failed", profile)
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
            if not profile:
                logger.info(
                    "No profile match for card '%s' (labels=%s) — skipping",
                    card.title, card.labels,
                )
                continue
            eligible, reason = self._card_is_for_me(card, profile)
            if not eligible:
                # Quiet log — another orchestrator (host or another node) is the
                # intended owner. Filtering here is intentional and not an error.
                logger.debug("Card '%s' not for this orchestrator — %s", card.title, reason)
                continue
            matched.append(card)

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
        KANBAN_PROFILES_DIR    path to profiles directory (default: agents/kanban/profiles/examples)
        KANBAN_POLL_INTERVAL   seconds between polls (default: 60)
        KANBAN_DRY_RUN         set to "1" to skip actual agent execution
        KANBAN_AUDIT_LOG       path to audit JSONL file (default: logs/kanban_audit.jsonl)
        KANBAN_NUM_AGENTS      number of concurrent agent workers on this host (default: 1)
        KANBAN_PROFILE_FILTER  only process cards whose resolved profile id matches this
                               (e.g. 'agent:default', 'agent:code'). When unset, the
                               orchestrator handles every profile (legacy single-host mode).
        KANBAN_HW_LABELS       comma-separated `hw:*` labels this orchestrator satisfies.
                               When unset, auto-detected from platform.system() —
                               darwin gets {hw:darwin, hw:macos}, linux gets {hw:linux},
                               windows gets {hw:windows}.
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

    profile_filter = os.environ.get("KANBAN_PROFILE_FILTER") or None
    hw_labels_env = os.environ.get("KANBAN_HW_LABELS")
    hw_labels = (
        {x.strip() for x in hw_labels_env.split(",") if x.strip()}
        if hw_labels_env
        else None  # auto-detect
    )

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
        provider_config=provider_config,
        profile_filter=profile_filter,
        hw_labels=hw_labels,
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
    parser.add_argument(
        "--profile", type=str, default=None,
        help="Restrict to one profile id (e.g. 'agent:default', 'agent:code'). "
             "When set, this orchestrator only claims cards whose resolved profile matches. "
             "Overrides KANBAN_PROFILE_FILTER env var.",
    )
    parser.add_argument(
        "--hw", type=str, default=None,
        help="Comma-separated hw:* labels this orchestrator satisfies "
             "(e.g. 'hw:linux,hw:gpu'). When unset, auto-detects from the host OS. "
             "Overrides KANBAN_HW_LABELS env var.",
    )
    args = parser.parse_args()

    # Load .env file if present
    env_file = Path(".env/agents.env")
    if not env_file.exists():
        env_file = Path(".env/apps.env")
    if env_file.exists():
        _load_dotenv(env_file)

    # CLI overrides for routing — set env vars BEFORE from_env() reads them.
    if args.profile:
        os.environ["KANBAN_PROFILE_FILTER"] = args.profile
    if args.hw:
        os.environ["KANBAN_HW_LABELS"] = args.hw

    orch = from_env(profiles_dir=args.profiles_dir)
    if args.poll_interval:
        orch.poll_interval = args.poll_interval
    if args.dry_run:
        orch.dry_run = True
    if args.num_agents is not None:
        orch.num_agents = max(1, args.num_agents)

    orch.run()
