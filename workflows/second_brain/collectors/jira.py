"""Read-only Jira collector for recently changed owner-relevant issues."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from workflows.second_brain.models import FeedItem, isoformat


_PRIORITY_SCORE = {"highest": 92, "high": 82, "medium": 68, "low": 55, "lowest": 45}


def _field_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("value") or "")
    return str(value or "")


def normalize_jira_issues(response: Any, *, domain: str = "", correlation_id: str) -> list[FeedItem]:
    raw_issues = response.get("issues", []) if isinstance(response, dict) else []
    items: list[FeedItem] = []
    for issue in raw_issues:
        if not isinstance(issue, dict):
            continue
        key = str(issue.get("key") or "").strip()
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        summary = str(fields.get("summary") or "").strip()
        if not key or not summary:
            continue
        status = _field_name(fields.get("status")) or "Unknown"
        priority_name = _field_name(fields.get("priority")) or "Medium"
        updated = str(fields.get("updated") or "")
        assignee = fields.get("assignee") if isinstance(fields.get("assignee"), dict) else {}
        assignee_name = str(assignee.get("displayName") or assignee.get("name") or "Unassigned")
        link = f"https://{domain.strip('/')}/browse/{key}" if domain else ""
        links = {"jira": link} if link else {}
        items.append(
            FeedItem(
                logical_key=f"jira:{key}",
                category="work",
                kind="jira_changed",
                title=f"{key} · {summary[:180]}",
                summary=f"{status} · {priority_name} · {assignee_name}",
                details=f"Jira reported this issue as recently updated. Last source update: {updated or 'unknown'}.",
                priority=_PRIORITY_SCORE.get(priority_name.casefold(), 65),
                confidence=1.0,
                status="fresh",
                source_refs=(f"jira:{key}",),
                source_at=updated,
                fresh_until=isoformat(datetime.now(timezone.utc) + timedelta(minutes=15)),
                expires_at=isoformat(datetime.now(timezone.utc) + timedelta(hours=24)),
                sensitivity="internal",
                allowed_clients=("web", "telegram", "cli", "rainmeter"),
                links=links,
                reason_codes=("recent-jira-change",),
                correlation_id=correlation_id,
            )
        )
    return items


def collect_jira_changed(
    *,
    cfg_id: str = "JIRA",
    hours: int = 8,
    max_results: int = 25,
    correlation_id: str,
) -> list[FeedItem]:
    """Fetch owner-relevant Jira changes without mutating Jira."""
    from apps.apps_config import CONFIG_MANAGER
    from apps.jira.references.web.api.issues import ApiServiceJiraIssues

    safe_hours = max(1, min(168, int(hours)))
    safe_limit = max(1, min(100, int(max_results)))
    config = CONFIG_MANAGER.get(cfg_id)
    service = ApiServiceJiraIssues(config)
    response = service.search_issues(
        jql=(
            "(assignee = currentUser() OR reporter = currentUser() OR watcher = currentUser()) "
            f"AND updated >= -{safe_hours}h ORDER BY updated DESC"
        ),
        max_results=safe_limit,
        fields=["summary", "status", "assignee", "priority", "updated"],
    )
    return normalize_jira_issues(
        response,
        domain=str(config.app_data.get("domain") or ""),
        correlation_id=correlation_id,
    )
