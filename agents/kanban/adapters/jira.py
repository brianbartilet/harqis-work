"""
Jira adapter — implements KanbanProvider against the Jira REST API.

Supports both Jira Cloud (v3) and Jira Data Center / Server (v2).
Uses basic auth (email + API token for Cloud, username + password for DC).

Credentials from env vars:
    JIRA_SERVER       e.g. https://yourcompany.atlassian.net
    JIRA_EMAIL        e.g. brian@example.com
    JIRA_API_TOKEN    Jira Cloud API token or DC password

Jira concept mapping:
    Board     → Jira Board (Scrum or Kanban)
    Column    → Status name (To Do, In Progress, Done ...)
    Card      → Issue
    Label     → Issue Label
    Checklist → Subtasks
    Comment   → Issue Comment
    Attachment→ Issue Attachment
    Assignee  → Issue Assignee
"""

import logging
from base64 import b64encode
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


class JiraProvider(KanbanProvider):
    def __init__(
        self,
        server: str,
        email: str,
        api_token: str,
        api_version: str = "3",
        timeout: int = 15,
    ):
        self._server = server.rstrip("/")
        self._base = f"{self._server}/rest/api/{api_version}"
        token = b64encode(f"{email}:{api_token}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._timeout = timeout

    def _get(self, path: str, **params) -> dict | list:
        r = requests.get(
            f"{self._base}{path}",
            headers=self._headers,
            params=params,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json: dict) -> dict:
        r = requests.post(
            f"{self._base}{path}",
            headers=self._headers,
            json=json,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json() if r.content else {}

    def _put(self, path: str, json: dict) -> None:
        r = requests.put(
            f"{self._base}{path}",
            headers=self._headers,
            json=json,
            timeout=self._timeout,
        )
        r.raise_for_status()

    # ── Columns ───────────────────────────────────────────────────────────────

    def get_columns(self, board_id: str) -> list[KanbanColumn]:
        # board_id here is the Jira project key (e.g. "HARQ")
        data = self._get(f"/project/{board_id}/statuses")
        seen: dict[str, str] = {}
        for issue_type in data:
            for status in issue_type.get("statuses", []):
                seen[status["name"]] = status["id"]
        return [KanbanColumn(id=v, name=k) for k, v in seen.items()]

    def get_column_by_name(self, board_id: str, name: str) -> Optional[KanbanColumn]:
        for col in self.get_columns(board_id):
            if col.name == name:
                return col
        return None

    # ── Cards ─────────────────────────────────────────────────────────────────

    def get_cards(
        self,
        board_id: str,
        column: str,
        label: Optional[str] = None,
    ) -> list[KanbanCard]:
        jql = f'project = "{board_id}" AND status = "{column}"'
        if label:
            jql += f' AND labels = "{label}"'
        data = self._get("/search", jql=jql, maxResults=50, fields="*all", expand="renderedFields")
        return [self._map_card(issue) for issue in data.get("issues", [])]

    def get_card(self, card_id: str) -> KanbanCard:
        data = self._get(f"/issue/{card_id}", fields="*all", expand="renderedFields")
        return self._map_card(data)

    def move_card(self, card_id: str, column: str) -> None:
        transitions = self._get(f"/issue/{card_id}/transitions")
        target = next(
            (t for t in transitions.get("transitions", []) if t["name"] == column),
            None,
        )
        if not target:
            available = [t["name"] for t in transitions.get("transitions", [])]
            raise ValueError(
                f"No Jira transition '{column}' for issue {card_id}. "
                f"Available: {available}"
            )
        self._post(f"/issue/{card_id}/transitions", {"transition": {"id": target["id"]}})

    def assign_card(self, card_id: str, member_id: str) -> None:
        self._put(f"/issue/{card_id}/assignee", {"accountId": member_id})

    # ── Comments ──────────────────────────────────────────────────────────────

    def add_comment(self, card_id: str, text: str) -> None:
        self._post(
            f"/issue/{card_id}/comment",
            {"body": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            ]}},
        )

    def get_comments(self, card_id: str) -> list[str]:
        data = self._get(f"/issue/{card_id}/comment", orderBy="created")
        comments = data.get("comments", [])
        results = []
        for c in comments:
            body = c.get("body", {})
            if isinstance(body, str):
                results.append(body)
            else:
                # ADF — extract plain text from paragraphs
                texts = []
                for block in body.get("content", []):
                    for inline in block.get("content", []):
                        if inline.get("type") == "text":
                            texts.append(inline.get("text", ""))
                results.append("".join(texts))
        return results

    # ── Checklists (via subtasks) ──────────────────────────────────────────────

    def check_item(self, card_id: str, item_id: str, checked: bool = True) -> None:
        status = "Done" if checked else "To Do"
        self.move_card(item_id, status)

    # ── Attachments ───────────────────────────────────────────────────────────

    def get_attachments(self, card_id: str) -> list[KanbanAttachment]:
        issue = self._get(f"/issue/{card_id}", fields="attachment")
        return [
            KanbanAttachment(
                id=a["id"],
                name=a["filename"],
                url=a["content"],
                mime_type=a.get("mimeType", ""),
                bytes_size=a.get("size", 0),
            )
            for a in issue.get("fields", {}).get("attachment", [])
        ]

    def add_attachment(
        self,
        card_id: str,
        name: str,
        content: bytes,
        mime_type: str = "text/plain",
    ) -> None:
        headers = {k: v for k, v in self._headers.items() if k != "Content-Type"}
        headers["X-Atlassian-Token"] = "no-check"
        requests.post(
            f"{self._base}/issue/{card_id}/attachments",
            headers=headers,
            files={"file": (name, content, mime_type)},
            timeout=30,
        ).raise_for_status()

    # ── Labels ────────────────────────────────────────────────────────────────

    def add_label(self, card_id: str, label: str) -> None:
        issue = self._get(f"/issue/{card_id}", fields="labels")
        labels = list(issue.get("fields", {}).get("labels", []))
        if label not in labels:
            labels.append(label)
        self._put(f"/issue/{card_id}", {"fields": {"labels": labels}})

    def remove_label(self, card_id: str, label: str) -> None:
        issue = self._get(f"/issue/{card_id}", fields="labels")
        labels = [lb for lb in issue.get("fields", {}).get("labels", []) if lb != label]
        self._put(f"/issue/{card_id}", {"fields": {"labels": labels}})

    # ── Custom Fields ─────────────────────────────────────────────────────────

    def get_custom_fields(self, card_id: str) -> dict[str, str]:
        issue = self._get(f"/issue/{card_id}", fields="*all")
        fields = issue.get("fields", {})
        return {
            k: str(v)
            for k, v in fields.items()
            if k.startswith("customfield_") and v is not None
        }

    def set_custom_field(self, card_id: str, field_name: str, value: str) -> None:
        self._put(f"/issue/{card_id}", {"fields": {field_name: value}})

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def register_webhook(self, board_id: str, callback_url: str) -> str:
        data = self._post(
            "/webhook",
            {
                "name": f"kanban-agent-{board_id}",
                "url": callback_url,
                "events": ["jira:issue_created", "jira:issue_updated"],
                "filters": {"issue-related-events-section": f"project = {board_id}"},
                "excludeBody": False,
            },
        )
        return str(data.get("self", ""))

    # ── Mappers ───────────────────────────────────────────────────────────────

    def _map_card(self, raw: dict) -> KanbanCard:
        f = raw.get("fields", {})
        assignee = f.get("assignee")
        return KanbanCard(
            id=raw["key"],
            title=f.get("summary", ""),
            description=self._extract_text(f.get("description")),
            labels=list(f.get("labels", [])),
            assignees=[assignee["accountId"]] if assignee else [],
            column=f.get("status", {}).get("name", ""),
            url=f"{self._server}/browse/{raw['key']}",
            checklists=self._map_subtasks(f.get("subtasks", [])),
            attachments=[
                KanbanAttachment(
                    id=a["id"],
                    name=a["filename"],
                    url=a["content"],
                    mime_type=a.get("mimeType", ""),
                    bytes_size=a.get("size", 0),
                )
                for a in f.get("attachment", [])
            ],
            custom_fields={
                k: str(v)
                for k, v in f.items()
                if k.startswith("customfield_") and v is not None
            },
            due_date=f.get("duedate"),
            raw=raw,
        )

    @staticmethod
    def _map_subtasks(subtasks: list) -> list[KanbanChecklist]:
        if not subtasks:
            return []
        items = [
            KanbanChecklistItem(
                id=s["key"],
                name=s.get("fields", {}).get("summary", s["key"]),
                checked=s.get("fields", {}).get("status", {}).get("name") == "Done",
            )
            for s in subtasks
        ]
        return [KanbanChecklist(id="subtasks", name="Subtasks", items=items)]

    @staticmethod
    def _extract_text(body) -> str:
        if body is None:
            return ""
        if isinstance(body, str):
            return body
        # ADF document
        parts = []
        for block in body.get("content", []):
            for inline in block.get("content", []):
                if inline.get("type") == "text":
                    parts.append(inline.get("text", ""))
            parts.append("\n")
        return "".join(parts).strip()
