"""
Trello adapter — implements KanbanProvider against the Trello REST API v1.

Credentials come from env vars:
    TRELLO_API_KEY
    TRELLO_API_TOKEN
"""

import logging
from typing import Optional

import requests

from agents.kanban.interface import (
    KanbanAttachment,
    KanbanCard,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanColumn,
    KanbanProvider,
)

logger = logging.getLogger(__name__)

_BASE = "https://api.trello.com/1"


class TrelloProvider(KanbanProvider):
    def __init__(self, api_key: str, token: str, timeout: int = 10):
        self._auth = {"key": api_key, "token": token}
        self._timeout = timeout
        # board_id → {column_name: list_id}
        self._col_cache: dict[str, dict[str, str]] = {}
        # short_link → full_id cache
        self._id_cache: dict[str, str] = {}

    def _resolve_board_id(self, board_id: str) -> str:
        """Resolve a short link (8 chars) to the full 24-char board ID if needed."""
        if len(board_id) == 24:
            return board_id
        if board_id in self._id_cache:
            return self._id_cache[board_id]
        r = requests.get(
            f"{_BASE}/boards/{board_id}",
            params={**self._auth, "fields": "id"},
            timeout=self._timeout,
        )
        r.raise_for_status()
        full_id = r.json()["id"]
        self._id_cache[board_id] = full_id
        logger.debug("Resolved board short link %s → %s", board_id, full_id)
        return full_id

    # ── Column helpers ────────────────────────────────────────────────────────

    def _refresh_columns(self, board_id: str) -> dict[str, str]:
        full_id = self._resolve_board_id(board_id)
        r = requests.get(
            f"{_BASE}/boards/{full_id}/lists",
            params=self._auth,
            timeout=self._timeout,
        )
        r.raise_for_status()
        mapping = {lst["name"]: lst["id"] for lst in r.json()}
        self._col_cache[board_id] = mapping
        return mapping

    def _resolve_col_id(self, board_id: str, name: str) -> str:
        if board_id not in self._col_cache:
            self._refresh_columns(board_id)
        col_id = self._col_cache[board_id].get(name)
        if not col_id:
            col_id = self._refresh_columns(board_id).get(name)
        if not col_id:
            raise ValueError(f"Column '{name}' not found on Trello board {board_id}")
        return col_id

    # ── KanbanProvider implementation ─────────────────────────────────────────

    def get_columns(self, board_id: str) -> list[KanbanColumn]:
        m = self._refresh_columns(board_id)
        return [KanbanColumn(id=v, name=k) for k, v in m.items()]

    def get_column_by_name(self, board_id: str, name: str) -> Optional[KanbanColumn]:
        try:
            col_id = self._resolve_col_id(board_id, name)
            return KanbanColumn(id=col_id, name=name)
        except ValueError:
            return None

    def get_cards(
        self,
        board_id: str,
        column: str,
        label: Optional[str] = None,
    ) -> list[KanbanCard]:
        col_id = self._resolve_col_id(board_id, column)
        r = requests.get(
            f"{_BASE}/lists/{col_id}/cards",
            params={
                **self._auth,
                "customFieldItems": "true",
                "attachments": "true",
                "checklists": "all",
            },
            timeout=self._timeout,
        )
        r.raise_for_status()
        cards = [self._map_card(c) for c in r.json()]
        if label:
            cards = [c for c in cards if label in c.labels]
        return cards

    def get_card(self, card_id: str) -> KanbanCard:
        r = requests.get(
            f"{_BASE}/cards/{card_id}",
            params={
                **self._auth,
                "customFieldItems": "true",
                "attachments": "true",
                "checklists": "all",
            },
            timeout=self._timeout,
        )
        r.raise_for_status()
        return self._map_card(r.json())

    def move_card(self, card_id: str, column: str) -> None:
        # Need board ID to resolve column name → list ID
        r = requests.get(
            f"{_BASE}/cards/{card_id}",
            params=self._auth,
            timeout=self._timeout,
        )
        r.raise_for_status()
        board_id = r.json()["idBoard"]
        col_id = self._resolve_col_id(board_id, column)
        requests.put(
            f"{_BASE}/cards/{card_id}",
            params={**self._auth, "idList": col_id},
            timeout=self._timeout,
        ).raise_for_status()
        logger.debug("Moved card %s → %s (%s)", card_id, column, col_id)

    def assign_card(self, card_id: str, member_id: str) -> None:
        requests.post(
            f"{_BASE}/cards/{card_id}/idMembers",
            params={**self._auth, "value": member_id},
            timeout=self._timeout,
        ).raise_for_status()

    def add_comment(self, card_id: str, text: str) -> None:
        requests.post(
            f"{_BASE}/cards/{card_id}/actions/comments",
            params={**self._auth, "text": text},
            timeout=self._timeout,
        ).raise_for_status()

    def get_comments(self, card_id: str) -> list[str]:
        r = requests.get(
            f"{_BASE}/cards/{card_id}/actions",
            params={**self._auth, "filter": "commentCard"},
            timeout=self._timeout,
        )
        r.raise_for_status()
        return [a["data"]["text"] for a in reversed(r.json())]

    def check_item(self, card_id: str, item_id: str, checked: bool = True) -> None:
        state = "complete" if checked else "incomplete"
        requests.put(
            f"{_BASE}/cards/{card_id}/checkItem/{item_id}",
            params={**self._auth, "state": state},
            timeout=self._timeout,
        ).raise_for_status()

    def get_attachments(self, card_id: str) -> list[KanbanAttachment]:
        r = requests.get(
            f"{_BASE}/cards/{card_id}/attachments",
            params=self._auth,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return [self._map_attachment(a) for a in r.json()]

    def add_attachment(
        self,
        card_id: str,
        name: str,
        content: bytes,
        mime_type: str = "text/plain",
    ) -> None:
        requests.post(
            f"{_BASE}/cards/{card_id}/attachments",
            params=self._auth,
            files={"file": (name, content, mime_type)},
            timeout=30,
        ).raise_for_status()

    def add_label(self, card_id: str, label: str) -> None:
        """Attach a label by name to a card.

        Trello's label model is per-board: every card-label association is
        actually a reference to a board-scoped label record. We resolve the
        label name on the card's board, creating the label if it doesn't
        exist yet, then attach it to the card. No-op if already attached.
        """
        board_id = self._resolve_card_board_id(card_id)
        label_id = self._resolve_or_create_label_id(board_id, label)
        # Skip the round-trip if it's already attached.
        if self._card_has_label(card_id, label_id):
            logger.debug("Card %s already has label '%s' (%s)", card_id, label, label_id)
            return
        r = requests.post(
            f"{_BASE}/cards/{card_id}/idLabels",
            params={**self._auth, "value": label_id},
            timeout=self._timeout,
        )
        r.raise_for_status()
        logger.debug("Added label '%s' (%s) to card %s", label, label_id, card_id)

    def remove_label(self, card_id: str, label: str) -> None:
        """Detach a label by name from a card. No-op if not attached."""
        board_id = self._resolve_card_board_id(card_id)
        try:
            label_id = self._resolve_label_id(board_id, label)
        except KeyError:
            logger.debug("Label '%s' does not exist on board %s — nothing to remove", label, board_id)
            return
        if not self._card_has_label(card_id, label_id):
            logger.debug("Card %s does not carry label '%s' — no-op", card_id, label)
            return
        r = requests.delete(
            f"{_BASE}/cards/{card_id}/idLabels/{label_id}",
            params=self._auth,
            timeout=self._timeout,
        )
        # Trello returns 200 on success and a slightly weird 400 if the label
        # isn't attached — guard against the race-condition path.
        if r.status_code == 400 and "does not exist" in r.text.lower():
            return
        r.raise_for_status()
        logger.debug("Removed label '%s' (%s) from card %s", label, label_id, card_id)

    # ── Label helpers ─────────────────────────────────────────────────────────

    def _resolve_card_board_id(self, card_id: str) -> str:
        r = requests.get(
            f"{_BASE}/cards/{card_id}",
            params={**self._auth, "fields": "idBoard"},
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()["idBoard"]

    def _board_labels(self, board_id: str) -> list[dict]:
        r = requests.get(
            f"{_BASE}/boards/{board_id}/labels",
            params={**self._auth, "fields": "id,name,color", "limit": 1000},
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()

    def _resolve_label_id(self, board_id: str, label: str) -> str:
        for lb in self._board_labels(board_id):
            if lb.get("name") == label:
                return lb["id"]
        raise KeyError(label)

    def _resolve_or_create_label_id(self, board_id: str, label: str) -> str:
        try:
            return self._resolve_label_id(board_id, label)
        except KeyError:
            r = requests.post(
                f"{_BASE}/labels",
                params={
                    **self._auth,
                    "name": label,
                    "color": "null",          # uncoloured — readable on every Trello theme
                    "idBoard": board_id,
                },
                timeout=self._timeout,
            )
            r.raise_for_status()
            new_id = r.json()["id"]
            logger.info("Created Trello label '%s' (%s) on board %s", label, new_id, board_id)
            return new_id

    def _card_has_label(self, card_id: str, label_id: str) -> bool:
        r = requests.get(
            f"{_BASE}/cards/{card_id}",
            params={**self._auth, "fields": "idLabels"},
            timeout=self._timeout,
        )
        r.raise_for_status()
        return label_id in r.json().get("idLabels", [])

    def get_custom_fields(self, card_id: str) -> dict[str, str]:
        r = requests.get(
            f"{_BASE}/cards/{card_id}",
            params={**self._auth, "customFieldItems": "true"},
            timeout=self._timeout,
        )
        r.raise_for_status()
        items = r.json().get("customFieldItems", [])
        return {
            f["idCustomField"]: str(f.get("value", {}).get("text", ""))
            for f in items
        }

    def set_custom_field(self, card_id: str, field_name: str, value: str) -> None:
        logger.warning("set_custom_field: field ID resolution not implemented in POC — skipping")

    def register_webhook(self, board_id: str, callback_url: str) -> str:
        r = requests.post(
            f"{_BASE}/webhooks",
            params={
                **self._auth,
                "callbackURL": callback_url,
                "idModel": board_id,
            },
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()["id"]

    def delete_webhook(self, webhook_id: str) -> None:
        requests.delete(
            f"{_BASE}/webhooks/{webhook_id}",
            params=self._auth,
            timeout=self._timeout,
        ).raise_for_status()

    # ── Mappers ───────────────────────────────────────────────────────────────

    def _map_card(self, raw: dict) -> KanbanCard:
        return KanbanCard(
            id=raw["id"],
            title=raw["name"],
            description=raw.get("desc", ""),
            labels=[lb["name"] for lb in raw.get("labels", [])],
            assignees=raw.get("idMembers", []),
            column=raw.get("idList", ""),
            url=raw.get("shortUrl", ""),
            checklists=[self._map_checklist(cl) for cl in raw.get("checklists", [])],
            attachments=[self._map_attachment(a) for a in raw.get("attachments", [])],
            custom_fields={
                f["idCustomField"]: str(f.get("value", {}).get("text", ""))
                for f in raw.get("customFieldItems", [])
            },
            due_date=raw.get("due"),
            raw=raw,
        )

    @staticmethod
    def _map_checklist(raw: dict) -> KanbanChecklist:
        return KanbanChecklist(
            id=raw["id"],
            name=raw["name"],
            items=[
                KanbanChecklistItem(
                    id=item["id"],
                    name=item["name"],
                    checked=item.get("state") == "complete",
                )
                for item in raw.get("checkItems", [])
            ],
        )

    @staticmethod
    def _map_attachment(raw: dict) -> KanbanAttachment:
        return KanbanAttachment(
            id=raw["id"],
            name=raw.get("name", ""),
            url=raw.get("url", ""),
            mime_type=raw.get("mimeType", ""),
            is_inline=raw.get("isUpload", False),
            bytes_size=raw.get("bytes", 0) or 0,
        )
