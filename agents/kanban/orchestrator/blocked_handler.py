"""
BlockedCardHandler — polls the 'Blocked' column and re-queues cards
when their blocking dependencies are resolved.

The maintainer resolves a block by adding missing secrets to the env file
and restarting the orchestrator (or signalling it). On the next blocked poll,
this handler detects the secrets are now present and moves the card back to
Backlog so the agent picks it up again.
"""

from __future__ import annotations

import logging

from agents.kanban.dependencies.detector import DependencyDetector
from agents.kanban.interface import KanbanCard, KanbanProvider
from agents.kanban.security.audit import AuditLogger, NullAuditLogger

logger = logging.getLogger(__name__)


class BlockedCardHandler:
    """
    Polls the BLOCKED column and re-queues cards whose dependencies are met.
    """

    BLOCKED_COLUMN = "Blocked"
    BACKLOG_COLUMN = "Backlog"

    def __init__(
        self,
        provider: KanbanProvider,
        board_id: str,
        audit: AuditLogger | None = None,
    ):
        self.provider = provider
        self.board_id = board_id
        self._detector = DependencyDetector()
        self._audit = audit or NullAuditLogger()

    def poll_once(self) -> int:
        """
        Check all BLOCKED cards. Returns the number re-queued to Backlog.
        """
        try:
            cards = self.provider.get_cards(self.board_id, self.BLOCKED_COLUMN)
        except Exception as e:
            logger.error("Failed to fetch Blocked column: %s", e)
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
        self.provider.add_comment(
            card.id,
            "## Agent: Dependencies Resolved\n\n"
            "All required environment variables and secrets are now available. "
            "Moving back to Backlog for retry.",
        )
        self.provider.move_card(card.id, self.BACKLOG_COLUMN)
        logger.info("Re-queued blocked card '%s' → Backlog", card.title)
        self._audit.card_lifecycle(self.BLOCKED_COLUMN, self.BACKLOG_COLUMN)
