"""
BlockedCardHandler — polls the 'Blocked' column and re-queues cards
when their blocking dependencies are resolved.

The maintainer resolves a block by adding missing secrets to the env file
and restarting the orchestrator (or signalling it). On the next blocked poll,
this handler detects the secrets are now present and moves the card back to
`Ready` so the agent picks it up again.
"""

from __future__ import annotations

import logging

from agents.projects.dependencies.detector import DependencyDetector
from agents.projects.orchestrator.lists import Lists, REQUEUE_LIST
from agents.projects.security.audit import AuditLogger, NullAuditLogger
from agents.projects.trello.client import TrelloClient
from agents.projects.trello.models import KanbanCard

logger = logging.getLogger(__name__)


class BlockedCardHandler:
    """Polls the BLOCKED column and re-queues cards whose dependencies are met."""

    def __init__(
        self,
        client: TrelloClient,
        board_id: str,
        audit: AuditLogger | None = None,
    ):
        self.client = client
        self.board_id = board_id
        self._detector = DependencyDetector()
        self._audit = audit or NullAuditLogger()

    def poll_once(self) -> int:
        """Check all BLOCKED cards. Returns the number re-queued to Ready."""
        try:
            cards = self.client.get_cards(self.board_id, Lists.BLOCKED)
        except Exception as e:
            logger.error("Failed to fetch Blocked column on board %s: %s", self.board_id, e)
            return 0

        re_queued = 0
        for card in cards:
            try:
                if self._is_resolved(card):
                    self._requeue(card)
                    re_queued += 1
                else:
                    logger.debug(
                        "Card '%s' still blocked — dependencies unmet", card.title
                    )
            except Exception as e:
                logger.error("Error checking blocked card '%s': %s", card.title, e)

        return re_queued

    def _is_resolved(self, card: KanbanCard) -> bool:
        result = self._detector.detect(card)
        return not result.has_blocking

    def _requeue(self, card: KanbanCard) -> None:
        self.client.add_comment(
            card.id,
            "## Agent: Dependencies Resolved\n\n"
            "All required environment variables and secrets are now available. "
            f"Moving back to {REQUEUE_LIST} for retry.",
        )
        self.client.move_card(card.id, REQUEUE_LIST)
        logger.info("Re-queued blocked card '%s' → %s", card.title, REQUEUE_LIST)
        self._audit.card_lifecycle(Lists.BLOCKED, REQUEUE_LIST)
