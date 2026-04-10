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

    # ── Column helpers ────────────────────────────────────────────────────────

    def _refresh_columns(self, board_id: str) -> dict[str, str]:
        r = requests.get(
            f"{_BASE}/boards/{board_id}/lists",
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
        logger.warning("add_label: label ID resolution not implemented in POC — skipping")

    def remove_label(self, card_id: str, label: str) -> None:
        logger.warning("remove_label: label ID resolution not implemented in POC — skipping")

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
