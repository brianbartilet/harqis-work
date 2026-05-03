"""
BoardOrchestrator — single-board polling + agent dispatch.

Holds per-board state (column cache via TrelloClient, blocked-handler) but
shares the heavyweight collaborators (TrelloClient, ProfileRegistry,
SecretStore, AuditLogger) with the WorkspaceOrchestrator that owns it.

This is what the old `LocalOrchestrator` was, minus the env loading and the
poll loop — those moved up to `WorkspaceOrchestrator` and `local.py` so
multiple boards share one process.
"""

from __future__ import annotations

import logging
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from agents.projects.agent.base import AgentExecutionError, BaseKanbanAgent
from agents.projects.agent.persona import sign_comment
from agents.projects.agent.question import (
    AgentPausedForQuestion,
    QUESTION_LABEL,
    REMEMBER_LABEL,
    build_recap_prompt,
    extract_state,
    find_resume_signal,
)
from agents.projects.dependencies.detector import DependencyDetector
from agents.projects.integrations import telemetry
from agents.projects.orchestrator.blocked_handler import BlockedCardHandler
from agents.projects.orchestrator.lists import (
    INTAKE_LIST,
    Lists,
    success_destination,
)
from agents.projects.orchestrator.routing import (
    card_os_required,
    is_human_card,
)
from agents.projects.profiles.registry import ProfileRegistry
from agents.projects.profiles.schema import AgentProfile
from agents.projects.security.audit import AuditLogger
from agents.projects.security.secret_store import SecretStore
from agents.projects.trello.client import TrelloClient
from agents.projects.trello.models import KanbanCard

logger = logging.getLogger(__name__)


class BoardOrchestrator:
    """Polls one Trello board, claims eligible cards, runs agents."""

    def __init__(
        self,
        client: TrelloClient,
        registry: ProfileRegistry,
        api_key: str,
        board_id: str,
        secret_store: SecretStore,
        audit_log_path: Path,
        os_labels: set[str],
        profile_filter: Optional[str] = None,
        dry_run: bool = False,
        num_agents: int = 1,
        # Mode A — per-profile clients shared across the workspace, so
        # one Trello account login is reused on every board.
        profile_clients: Optional[dict[str, TrelloClient]] = None,
        client_factory: Optional[callable] = None,
    ):
        self.client = client
        self.registry = registry
        self.api_key = api_key
        self.board_id = board_id
        self._secret_store = secret_store
        self._audit_log_path = audit_log_path
        self.os_labels = os_labels
        self.profile_filter = profile_filter
        self.dry_run = dry_run
        self.num_agents = max(1, num_agents)

        self._dep_detector = DependencyDetector()
        self._blocked_handler = BlockedCardHandler(client, board_id)
        self._profile_clients: dict[str, TrelloClient] = (
            profile_clients if profile_clients is not None else {}
        )
        self._client_factory = client_factory

    # ── Routing ───────────────────────────────────────────────────────────────

    def _card_is_for_me(
        self, card: KanbanCard, profile: Optional[AgentProfile]
    ) -> tuple[bool, str]:
        """Return (eligible, reason). `reason` is a one-line log string when not eligible."""
        if self.profile_filter:
            if profile is None or profile.id != self.profile_filter:
                resolved = profile.id if profile else "(none)"
                return False, f"profile mismatch (card={resolved}, filter={self.profile_filter})"

        required_os = card_os_required(card)
        if required_os and not (required_os & self.os_labels):
            return False, (
                f"os mismatch (card needs {sorted(required_os)}, "
                f"this host satisfies {sorted(self.os_labels)})"
            )

        return True, ""

    # ── Per-profile client (Mode A) ──────────────────────────────────────────

    def client_for_profile(self, profile: AgentProfile) -> TrelloClient:
        """Return the TrelloClient for this profile.

        Mode A: when the profile declares `provider_credentials` AND the named
        env vars resolve to a real key/token, return a per-profile client built
        once and cached at the workspace level (so the same account login is
        reused across every board).

        Mode B: return the shared workspace client; comments are signed with
        the persona block by `_post_comment` instead.
        """
        creds = profile.provider_credentials
        if not creds.is_set() or self._client_factory is None:
            return self.client

        cached = self._profile_clients.get(profile.id)
        if cached is not None:
            return cached

        api_key = os.environ.get(creds.trello_api_key_env) if creds.trello_api_key_env else None
        token = os.environ.get(creds.trello_api_token_env) if creds.trello_api_token_env else None
        if not api_key or not token:
            logger.info(
                "Profile %s declares provider_credentials but env vars (%s / %s) "
                "are not set — falling back to shared client (Mode B).",
                profile.id, creds.trello_api_key_env, creds.trello_api_token_env,
            )
            return self.client

        per_profile = self._client_factory(api_key=api_key, token=token)
        self._profile_clients[profile.id] = per_profile
        logger.info("Mode A active for profile %s — using dedicated Trello account", profile.id)
        return per_profile

    def _post_comment(
        self, card_id: str, body: str, profile: Optional[AgentProfile] = None
    ) -> None:
        if profile is not None:
            target = self.client_for_profile(profile)
            using_mode_a = target is not self.client
            if not using_mode_a:
                body = sign_comment(profile, body)
        else:
            target = self.client
        target.add_comment(card_id, body)

    def _move(
        self, card_id: str, column: str, profile: Optional[AgentProfile] = None
    ) -> None:
        target = self.client_for_profile(profile) if profile else self.client
        target.move_card(card_id, column)

    # ── Single card processing ────────────────────────────────────────────────

    def process_card(self, card: KanbanCard) -> Optional[str]:
        """Claim a card, run its agent, post result, move forward.

        Returns the result text on success, None on skip/error. Successful
        cards land in `In Review` (or `Done` if the profile auto-approves).
        Failures land in `Failed`.
        """
        if is_human_card(card):
            logger.debug(
                "Skipping card %s — labelled human/manual/input (labels=%s)",
                card.id, card.labels,
            )
            return None

        profile = self.registry.resolve_for_card(card)
        if not profile:
            logger.debug("No profile for card %s (labels=%s)", card.id, card.labels)
            return None

        eligible, reason = self._card_is_for_me(card, profile)
        if not eligible:
            logger.debug("Skipping card %s — %s", card.id, reason)
            return None

        logger.info(
            "Processing card '%s' | board=%s | id=%s | profile=%s",
            card.title, self.board_id, card.id, profile.id,
        )

        if self.dry_run:
            logger.info("[DRY RUN] Would run %s on card %s", profile.id, card.id)
            return "[dry-run]"

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
                        "## Agent: Blocked\n\n"
                        "Cannot start — the following dependencies must be resolved by the maintainer:\n\n"
                        f"{summary}\n\n"
                        "Once resolved, the card will be automatically re-queued.",
                        profile,
                    )
                    self._move(card.id, Lists.BLOCKED, profile)
                    telemetry.emit_card_blocked(
                        board_id=self.board_id, card_id=card.id,
                        profile_id=profile.id, reason=summary,
                    )
                except Exception as e:
                    logger.error("Failed to block card %s: %s", card.id, e)
                return None

        try:
            scoped = self._secret_store.scoped_for_profile(profile)
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
                self._move(card.id, Lists.FAILED, profile)
            except Exception:
                pass
            return None

        audit = AuditLogger(
            agent_id=profile.id,
            card_id=card.id,
            log_path=self._audit_log_path,
        )
        audit.secret_access(profile.id, list(scoped.keys()))

        agent_client = self.client_for_profile(profile)

        try:
            self._move(card.id, Lists.PENDING, profile)
            self._post_comment(card.id, f"claimed-by: {profile.name}", profile)
            audit.card_lifecycle(INTAKE_LIST, Lists.PENDING)
            telemetry.emit_card_claimed(
                board_id=self.board_id, card_id=card.id, profile_id=profile.id,
            )
        except Exception as e:
            logger.error("Failed to claim card %s: %s", card.id, e)
            return None

        try:
            self._move(card.id, Lists.IN_PROGRESS, profile)
            audit.card_lifecycle(Lists.PENDING, Lists.IN_PROGRESS)
        except Exception as e:
            logger.warning("Could not move to '%s': %s", Lists.IN_PROGRESS, e)

        from time import time as _now  # local import keeps top imports tidy
        started = _now()
        telemetry.emit_agent_started(
            board_id=self.board_id, card_id=card.id,
            profile_id=profile.id, model_id=profile.model.model_id,
        )

        try:
            agent = BaseKanbanAgent(
                profile=profile,
                card=card,
                provider=agent_client,
                api_key=self.api_key,
                scoped_secrets=scoped,
                audit=audit,
            )
            result = agent.run()
        except AgentPausedForQuestion as paused:
            logger.info(
                "Card %s paused for human reply (stateful=%s)",
                card.id, paused.stateful,
            )
            audit.card_lifecycle(Lists.IN_PROGRESS, f"{Lists.IN_PROGRESS} (waiting)")
            telemetry.emit_card_paused(
                board_id=self.board_id, card_id=card.id,
                profile_id=profile.id, stateful=paused.stateful,
            )
            return f"[paused-for-question] {paused.question}"
        except Exception as e:
            self._handle_error(card, profile, e, audit)
            return None

        try:
            self._post_comment(card.id, f"## Result\n\n{result}", profile)
            destination = success_destination(profile)
            self._move(card.id, destination, profile)
            audit.card_lifecycle(Lists.IN_PROGRESS, destination)
            telemetry.emit_agent_finished(
                board_id=self.board_id, card_id=card.id, profile_id=profile.id,
                destination=destination, duration_seconds=_now() - started,
            )
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
            heading = {
                "api_usage_limit": "Agent Failed — Anthropic usage limit reached",
                "api_rate_limit":  "Agent Failed — Anthropic rate limit (transient)",
                "api_error":       "Agent Failed — Anthropic API error",
            }.get(exc.kind, f"Agent Failed — {exc.kind}")
            comment = f"## {heading}\n\n```\n{exc}\n```"
            kind = exc.kind
            logger.error("Agent failed on card %s (%s): %s", card.id, kind, exc)
        else:
            tb = traceback.format_exc()
            comment = f"## Agent Error\n\n```\n{tb}\n```"
            kind = "unknown"
            logger.error("Agent error on card %s:\n%s", card.id, tb)
        if audit:
            audit.agent_finish(success=False, iterations=0, detail=str(exc))
        try:
            self._post_comment(card.id, comment, profile)
            self._move(card.id, Lists.FAILED, profile)
        except Exception as post_err:
            logger.error("Could not post error comment: %s", post_err)
        telemetry.emit_agent_failed(
            board_id=self.board_id, card_id=card.id,
            profile_id=profile.id, kind=kind, detail=str(exc),
        )

    # ── Poll one board ────────────────────────────────────────────────────────

    def poll_intake(self) -> int:
        """Poll the intake column (Ready) once. Returns number of cards processed."""
        try:
            cards = self.client.get_cards(self.board_id, INTAKE_LIST)
        except Exception as e:
            logger.error("Failed to fetch %s on board %s: %s", INTAKE_LIST, self.board_id, e)
            return 0

        matched = []
        for card in cards:
            if is_human_card(card):
                logger.debug(
                    "Card '%s' off-limits (human/manual/input) — skipping",
                    card.title,
                )
                continue
            profile = self.registry.resolve_for_card(card)
            if not profile:
                logger.info(
                    "No profile match for card '%s' (labels=%s) — skipping",
                    card.title, card.labels,
                )
                continue
            eligible, reason = self._card_is_for_me(card, profile)
            if not eligible:
                logger.debug("Card '%s' not for this orchestrator — %s", card.title, reason)
                continue
            matched.append(card)

        if not matched:
            return 0

        if self.num_agents == 1:
            count = 0
            for card in matched:
                if self.process_card(card) is not None:
                    count += 1
            return count

        logger.info(
            "Dispatching %d card(s) across %d agent worker(s) on board %s",
            len(matched), self.num_agents, self.board_id,
        )
        count = 0
        with ThreadPoolExecutor(max_workers=self.num_agents) as pool:
            futures = {pool.submit(self.process_card, card): card for card in matched}
            for future in as_completed(futures):
                card = futures[future]
                try:
                    if future.result() is not None:
                        count += 1
                except Exception as e:
                    logger.error("Unhandled error processing card %s: %s", card.id, e)
        return count

    def poll_blocked(self) -> int:
        n = self._blocked_handler.poll_once()
        if n:
            logger.info("Re-queued %d blocked card(s) on board %s", n, self.board_id)
        return n

    # ── Resume (paused-for-question) ─────────────────────────────────────────

    def poll_resumes(self) -> int:
        """Scan In Progress for cards where a paused agent should resume."""
        try:
            cards = self.client.get_cards(self.board_id, Lists.IN_PROGRESS)
        except Exception as e:
            logger.debug("Could not fetch %s for resume scan on board %s: %s",
                         Lists.IN_PROGRESS, self.board_id, e)
            return 0

        resumed = 0
        for card in cards:
            if is_human_card(card):
                continue
            if QUESTION_LABEL not in (card.labels or []):
                continue
            profile = self.registry.resolve_for_card(card)
            if not profile:
                continue
            eligible, reason = self._card_is_for_me(card, profile)
            if not eligible:
                logger.debug("Resume candidate %s not for this orchestrator — %s", card.id, reason)
                continue
            try:
                comments = self.client.get_comments(card.id)
            except Exception as e:
                logger.warning("Could not read comments for resume on card %s: %s", card.id, e)
                continue
            signal = find_resume_signal(comments)
            if signal is None:
                continue
            try:
                if self.resume_card(card, profile, comments, signal):
                    resumed += 1
            except Exception as e:
                logger.error("Unhandled error resuming card %s: %s", card.id, e)
        return resumed

    def resume_card(
        self,
        card: KanbanCard,
        profile: AgentProfile,
        comments: list[str],
        signal: tuple[int, list[str]],
    ) -> bool:
        if self.dry_run:
            logger.info("[DRY RUN] Would resume card %s with profile %s", card.id, profile.id)
            return True

        question_idx, human_replies = signal
        question_comment = comments[question_idx]
        stateful = REMEMBER_LABEL in (card.labels or [])

        agent_client = self.client_for_profile(profile)

        try:
            agent_client.remove_label(card.id, QUESTION_LABEL)
        except Exception as e:
            logger.warning(
                "Could not remove %s label from card %s (continuing): %s",
                QUESTION_LABEL, card.id, e,
            )

        try:
            scoped = self._secret_store.scoped_for_profile(profile)
            if "ANTHROPIC_API_KEY" not in scoped:
                scoped["ANTHROPIC_API_KEY"] = self.api_key
        except KeyError as e:
            logger.error("Missing required secret for profile %s on resume: %s", profile.id, e)
            return False

        audit = AuditLogger(
            agent_id=profile.id,
            card_id=card.id,
            log_path=self._audit_log_path,
        )
        audit.secret_access(profile.id, list(scoped.keys()))

        prior_messages: Optional[list[dict]] = None
        prior_iteration = 0
        if stateful:
            payload = extract_state(comments)
            if payload:
                prior_messages = payload.get("messages") or None
                prior_iteration = int(payload.get("iteration", 0))
                logger.info(
                    "Resuming card %s in stateful mode (%d prior messages, iteration %d)",
                    card.id, len(prior_messages or []), prior_iteration,
                )
            else:
                logger.warning(
                    "Card %s has %s but no decodable state sidecar — falling back to stateless resume",
                    card.id, REMEMBER_LABEL,
                )

        if prior_messages is not None:
            resume_user_message = "\n\n".join(r.strip() for r in human_replies)
        else:
            resume_user_message = build_recap_prompt(question_comment, human_replies)

        logger.info(
            "Resuming agent %s on card %s (stateful=%s, replies=%d)",
            profile.id, card.id, prior_messages is not None, len(human_replies),
        )

        try:
            agent = BaseKanbanAgent(
                profile=profile,
                card=card,
                provider=agent_client,
                api_key=self.api_key,
                scoped_secrets=scoped,
                audit=audit,
                prior_messages=prior_messages,
                prior_iteration=prior_iteration,
                resume_user_message=resume_user_message,
            )
            result = agent.run()
        except AgentPausedForQuestion as paused:
            logger.info(
                "Card %s asked another question on resume (stateful=%s)",
                card.id, paused.stateful,
            )
            return True
        except Exception as e:
            self._handle_error(card, profile, e, audit)
            return False

        try:
            self._post_comment(card.id, f"## Result\n\n{result}", profile)
            destination = success_destination(profile)
            self._move(card.id, destination, profile)
            audit.card_lifecycle(Lists.IN_PROGRESS, destination)
            logger.info("Card %s → %s (after resume)", card.id, destination)
        except Exception as e:
            logger.error("Failed to post resume result for card %s: %s", card.id, e)
        return True
