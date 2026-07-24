"""Daily and retroactive Trello activity -> Homework-for-Life entries.

The collector reads actions authored by the authenticated Trello member via
``apps/trello``. One meaningful Trello action becomes one ``HflEntry`` with
the action's original Asia/Singapore timestamp and links back to Trello.
Routine actions are rendered deterministically; Haiku is used only when a
text-heavy or unfamiliar action benefits from summarization.

Authentication reuses ``TRELLO_API_KEY`` and ``TRELLO_API_TOKEN`` from the
existing app configuration. ``HFL_TRELLO_WORKSPACES`` optionally limits
collection to comma-separated Workspace IDs/slugs; an empty value or ``all``
includes every Workspace and personal boards. Missing credentials or an empty
window is a clean no-op. Every accepted entry is submitted through the shared
HFL persistence boundary, which dual-writes Markdown and Elasticsearch and
deduplicates on the Trello action ID.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.trello.config import CONFIG as TRELLO_CONFIG
from apps.trello.references.web.api.members import ApiServiceTrelloMembers
from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_trello")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_LOCAL_TZ = ZoneInfo("Asia/Singapore")
_DEFAULT_PROFILE = "https://trello.com/u/brianbartilet/activity"
_MAX_MEMBER_PAGES = 90  # stays below Trello's 100 /members requests per 15m
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization)"
    r"\s*[:=]\s*(\S+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Z0-9._~+/=-]+")

_KNOWN_ACTION_TYPES = {
    "addAttachmentToCard",
    "addChecklistToCard",
    "addLabelToCard",
    "addMemberToBoard",
    "addMemberToCard",
    "addToOrganizationBoard",
    "commentCard",
    "copyCard",
    "createBoard",
    "createCard",
    "createCheckItem",
    "createList",
    "deleteAttachmentFromCard",
    "deleteCheckItem",
    "moveCardFromBoard",
    "moveCardToBoard",
    "removeChecklistFromCard",
    "removeFromOrganizationBoard",
    "removeLabelFromCard",
    "removeMemberFromBoard",
    "removeMemberFromCard",
    "updateBoard",
    "updateCard",
    "updateCheckItem",
    "updateCheckItemStateOnCard",
    "updateList",
}


def _credentials_present() -> bool:
    data = getattr(TRELLO_CONFIG, "app_data", {}) or {}
    values = (str(data.get("api_key") or ""), str(data.get("api_token") or ""))
    return all(value.strip() and "${" not in value for value in values)


def _parse_day(value: str) -> date:
    return datetime.fromisoformat(str(value).strip()).date()


def resolve_trello_window(
    *,
    period: str = "",
    since: str = "",
    until: str = "",
    window_days: int = 1,
    today: Optional[date] = None,
) -> tuple[Optional[date], date, str]:
    """Resolve manual period vocabulary or the scheduled completed-day window."""
    now = today or datetime.now(_LOCAL_TZ).date()
    raw = re.sub(r"[\s_]+", "-", (period or "").strip().lower())
    if raw:
        if raw == "all":
            return None, now, "all"
        if raw in {"today"}:
            return now, now, "today"
        if raw in {"yesterday", "previous-day"}:
            day = now - timedelta(days=1)
            return day, day, "yesterday"
        if raw in {"last-year", "previous-year"}:
            year = now.year - 1
            return date(year, 1, 1), date(year, 12, 31), "last-year"
        match = re.fullmatch(r"last-(\d+)-days?", raw)
        if match:
            count = max(1, int(match.group(1)))
            return now - timedelta(days=count - 1), now, raw
        if re.fullmatch(r"\d{4}", raw):
            year = int(raw)
            return date(year, 1, 1), date(year, 12, 31), raw
        try:
            one_day = _parse_day(raw)
            return one_day, one_day, raw
        except ValueError as exc:
            raise ValueError(
                "period must be today, yesterday, last N days, last year, "
                "YYYY, YYYY-MM-DD, or all"
            ) from exc

    if since or until:
        start = _parse_day(since) if since else None
        end = _parse_day(until) if until else now
        if start and start > end:
            start, end = end, start
        return start, end, f"{start or 'beginning'}..{end}"

    count = max(1, int(window_days))
    end = now - timedelta(days=1)
    start = end - timedelta(days=count - 1)
    return start, end, f"previous-{count}-day(s)"


def _action_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_LOCAL_TZ)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").casefold()).strip("-")


def _workspace_selectors(workspaces: Optional[str | Iterable[str]]) -> set[str]:
    value: str | Iterable[str] = (
        os.environ.get("HFL_TRELLO_WORKSPACES", "")
        if workspaces is None
        else workspaces
    )
    parts = value.split(",") if isinstance(value, str) else list(value)
    selected = {
        str(item).strip().casefold()
        for item in parts
        if str(item).strip()
    }
    return set() if not selected or "all" in selected else selected


def _with_rate_limit_retry(call, /, *args, **kwargs):
    waits = (2, 5, 10)
    for attempt in range(len(waits) + 1):
        try:
            return call(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - service wrapper varies
            if "429" not in str(exc) or attempt >= len(waits):
                raise
            delay = waits[attempt]
            _log.warning("ingest_trello: rate limited; retrying in %ds", delay)
            time.sleep(delay)
    return []


def _workspace_context(
    action: dict,
    *,
    boards: dict[str, dict],
    organizations: dict[str, dict],
) -> dict[str, Any]:
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    action_board = data.get("board") if isinstance(data.get("board"), dict) else {}
    board = boards.get(str(action_board.get("id") or ""), {})
    merged_board = {**board, **action_board}
    action_org = (
        data.get("organization")
        if isinstance(data.get("organization"), dict)
        else {}
    )
    org_id = str(
        action_org.get("id")
        or merged_board.get("idOrganization")
        or ""
    )
    org = {**organizations.get(org_id, {}), **action_org}
    org_slug = str(org.get("name") or "")
    org_name = str(org.get("displayName") or org_slug)
    return {
        "id": org_id,
        "slug": org_slug,
        "name": org_name,
        "personal": not bool(org_id),
        "board": merged_board,
    }


def _workspace_allowed(context: dict, selected: set[str]) -> bool:
    if not selected:
        return True
    if context["personal"]:
        return "personal" in selected
    candidates = {
        str(context.get("id") or "").casefold(),
        str(context.get("slug") or "").casefold(),
        str(context.get("name") or "").casefold(),
        _slug(str(context.get("name") or "")),
    }
    return bool(selected & {candidate for candidate in candidates if candidate})


def _authored_by_member(action: dict, member: dict) -> bool:
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    if action.get("appCreator") or data.get("butler"):
        return False
    creator = (
        action.get("memberCreator")
        if isinstance(action.get("memberCreator"), dict)
        else {}
    )
    member_id = str(member.get("id") or "")
    creator_id = str(action.get("idMemberCreator") or creator.get("id") or "")
    if member_id and creator_id:
        return member_id == creator_id
    username = str(member.get("username") or "").casefold()
    creator_username = str(creator.get("username") or "").casefold()
    return bool(username and username == creator_username)


def _entity(data: dict, name: str) -> dict:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def _trello_references(
    action: dict,
    *,
    workspace: dict,
    username: str,
) -> tuple[str, ...]:
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    card = _entity(data, "card")
    board = workspace.get("board") or _entity(data, "board")
    action_id = str(action.get("id") or "")
    card_key = str(card.get("shortLink") or card.get("id") or "")
    board_key = str(board.get("shortLink") or board.get("id") or "")
    refs: list[str] = []
    if card_key:
        card_url = str(card.get("url") or f"https://trello.com/c/{card_key}")
        refs.append(f"{card_url}#action-{action_id}" if action_id else card_url)
        refs.append(card_url)
    if board_key:
        refs.append(str(board.get("url") or f"https://trello.com/b/{board_key}"))
    if workspace.get("slug"):
        refs.append(f"https://trello.com/w/{workspace['slug']}")
    refs.append(
        f"https://trello.com/u/{username}/activity"
        if username
        else _DEFAULT_PROFILE
    )
    return tuple(dict.fromkeys(ref for ref in refs if ref))


def _humanize_action_type(value: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value or "updated Trello")
    return words.replace("_", " ").strip().capitalize()


def _privacy_text(value: str) -> str:
    text = _EMAIL.sub("<redacted-email>", value or "")
    text = _BEARER.sub("Bearer <redacted>", text)
    return _SECRET_VALUE.sub(r"\1=<redacted>", text)


def _action_tags(action_type: str, workspace: dict, board_name: str) -> list[str]:
    if "Comment" in action_type or action_type == "commentCard":
        kind = "comment"
    elif "Check" in action_type:
        kind = "checklist"
    elif "Attachment" in action_type:
        kind = "attachment"
    elif "Label" in action_type:
        kind = "label"
    elif "Member" in action_type:
        kind = "membership"
    elif "Board" in action_type:
        kind = "board"
    elif "List" in action_type:
        kind = "list"
    else:
        kind = "card"
    tags = ["trello", kind]
    if workspace.get("slug") or workspace.get("name"):
        tags.append(f"workspace-{_slug(workspace.get('slug') or workspace.get('name'))}")
    if board_name:
        tags.append(f"board-{_slug(board_name)}")
    return [tag for tag in dict.fromkeys(tags) if tag and not tag.endswith("-")][:6]


def _format_action(action: dict) -> dict[str, Any]:
    data = action["data"]
    action_type = action["type"]
    card = _entity(data, "card")
    board = action["workspace"].get("board") or _entity(data, "board")
    list_data = _entity(data, "list")
    card_name = _privacy_text(str(card.get("name") or "card"))
    board_name = _privacy_text(str(board.get("name") or "Trello"))
    list_name = _privacy_text(str(list_data.get("name") or ""))
    old = _entity(data, "old")
    text = _privacy_text(str(data.get("text") or "").strip())

    moment = ""
    details = ""
    if action_type == "createCard":
        moment = f'Created “{card_name}”'
        details = f"Created the card on {board_name}" + (
            f" in {list_name}." if list_name else "."
        )
    elif action_type == "copyCard":
        moment = f'Copied “{card_name}”'
        details = f"Created a card copy on {board_name}."
    elif action_type == "commentCard":
        moment = f'Commented on “{card_name}”'
        details = text[:2000] or f"Added a comment on {board_name}."
    elif action_type == "updateCard":
        if "idList" in old or data.get("listBefore") or data.get("listAfter"):
            before = _privacy_text(str(
                _entity(data, "listBefore").get("name") or "another list"
            ))
            after = _privacy_text(str(
                _entity(data, "listAfter").get("name") or list_name or "a new list"
            ))
            moment = f'Moved “{card_name}” from {before} to {after}'
            details = f"Moved the card on {board_name}."
        elif "name" in old:
            old_name = _privacy_text(str(old.get("name") or "card"))
            moment = f'Renamed “{old_name}” to “{card_name}”'
            details = f"Renamed the card on {board_name}."
        elif "closed" in old:
            closed = bool(card.get("closed"))
            moment = f'{"Archived" if closed else "Reopened"} “{card_name}”'
            details = f'Changed the card status on {board_name}.'
        elif "dueComplete" in old:
            complete = bool(card.get("dueComplete"))
            moment = f'Marked “{card_name}” {"complete" if complete else "incomplete"}'
            details = f"Updated completion status on {board_name}."
        elif "due" in old:
            moment = f'Changed the due date for “{card_name}”'
            details = f"Updated the card deadline on {board_name}."
        elif "desc" in old:
            moment = f'Updated the description of “{card_name}”'
            details = f"Revised the card description on {board_name}."
        else:
            moment = f'Updated “{card_name}”'
            details = f"Changed card details on {board_name}."
    elif action_type == "updateCheckItemStateOnCard":
        check = _entity(data, "checkItem")
        complete = str(check.get("state") or "").casefold() == "complete"
        check_name = _privacy_text(str(check.get("name") or "a checklist item"))
        moment = f'{"Completed" if complete else "Reopened"} “{check_name}”'
        details = f'Updated the checklist on “{card_name}” in {board_name}.'
    elif action_type in {"createCheckItem", "updateCheckItem", "deleteCheckItem"}:
        check = _entity(data, "checkItem")
        check_name = _privacy_text(str(check.get("name") or "a checklist item"))
        verb = {
            "createCheckItem": "Added",
            "updateCheckItem": "Updated",
            "deleteCheckItem": "Removed",
        }[action_type]
        moment = f'{verb} checklist item “{check_name}”'
        details = f'Changed the checklist on “{card_name}” in {board_name}.'
    elif action_type in {"addAttachmentToCard", "deleteAttachmentFromCard"}:
        attachment = _entity(data, "attachment")
        attachment_name = _privacy_text(
            str(attachment.get("name") or "an attachment")
        )
        verb = "Attached" if action_type.startswith("add") else "Removed"
        moment = f'{verb} “{attachment_name}” {"to" if verb == "Attached" else "from"} “{card_name}”'
        details = f"Changed attachments on {board_name}; attachment contents were not ingested."
    elif action_type in {"addLabelToCard", "removeLabelFromCard"}:
        label = _entity(data, "label")
        label_name = _privacy_text(
            str(label.get("name") or label.get("color") or "a label")
        )
        verb = "Added" if action_type.startswith("add") else "Removed"
        moment = f'{verb} label “{label_name}” {"to" if verb == "Added" else "from"} “{card_name}”'
        details = f"Updated card labels on {board_name}."
    elif action_type in {"createList", "updateList"}:
        target = _privacy_text(str(list_data.get("name") or "a list"))
        moment = f'{"Created" if action_type == "createList" else "Updated"} list “{target}”'
        details = f"Changed the board structure on {board_name}."
    elif action_type in {"createBoard", "updateBoard"}:
        moment = f'{"Created" if action_type == "createBoard" else "Updated"} board “{board_name}”'
        details = "Changed a Trello board."
    else:
        subject = card_name if card else board_name
        moment = f"{_humanize_action_type(action_type)}: {subject}"
        details = f"Recorded a Trello {action_type} action."

    return {
        "skip": False,
        "moment": moment[:120],
        "what_happened": details,
        "why_it_stayed": "",
        "possible_use": "activity-log",
        "tags": _action_tags(action_type, action["workspace"], board_name),
        "synthesized": False,
    }


def _needs_synthesis(action: dict) -> bool:
    text = str(action.get("data", {}).get("text") or "")
    return len(text) > 280 or action.get("type") not in _KNOWN_ACTION_TYPES


def _safe_model_payload(action: dict, fallback: dict) -> dict[str, Any]:
    data = action["data"]
    return {
        "action_type": action["type"],
        "when": action["when"],
        "workspace": action["workspace"].get("name") or "personal",
        "board": (action["workspace"].get("board") or {}).get("name"),
        "list": _entity(data, "list").get("name"),
        "card": _entity(data, "card").get("name"),
        "routine_summary": fallback["moment"],
        "details": fallback["what_happened"],
    }


def distill_trello_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn one normalized Trello action into HFL fields."""
    fallback = _format_action(activity)
    if not synthesize:
        return fallback
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return fallback
        response = client.send_message(
            prompt=json.dumps(
                _safe_model_payload(activity, fallback),
                ensure_ascii=False,
                indent=2,
            ),
            system=load_prompt("ingest_trello").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = response.content[0].text if response and response.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return fallback
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [
            str(tag).strip().lstrip("#")
            for tag in (parsed.get("tags") or [])
            if str(tag).strip()
        ]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break Beat for LLM errors
        _log.warning("ingest_trello: synthesis failed (%s) — raw fallback", exc)
        return fallback


def collect_trello_activity(
    *,
    since: Optional[date],
    until: date,
    service: ApiServiceTrelloMembers,
    workspaces: Optional[str | Iterable[str]] = None,
    page_size: int = 200,
    max_actions: int = 10_000,
) -> dict[str, Any]:
    """Collect authored, workspace-filtered member actions in a date window."""
    page_size = max(1, min(int(page_size), 1000))
    max_actions = max(1, int(max_actions))
    selected = _workspace_selectors(workspaces)
    member = _with_rate_limit_retry(service.get_me) or {}
    boards_list = _with_rate_limit_retry(
        service.get_member_boards, member_id="me", filter="all"
    ) or []
    organizations_list = _with_rate_limit_retry(
        service.get_member_organizations, member_id="me"
    ) or []
    boards = {
        str(board.get("id")): board
        for board in boards_list
        if isinstance(board, dict) and board.get("id")
    }
    organizations = {
        str(org.get("id")): org
        for org in organizations_list
        if isinstance(org, dict) and org.get("id")
    }

    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    before: Optional[str] = None
    pages = 0
    scanned = 0
    reached_start = False
    last_page_full = False
    since_iso = (
        datetime.combine(since, datetime.min.time(), tzinfo=_LOCAL_TZ)
        .astimezone(timezone.utc)
        .isoformat()
        if since
        else None
    )

    while (
        len(actions) < max_actions
        and pages < _MAX_MEMBER_PAGES
        and not reached_start
    ):
        page = _with_rate_limit_retry(
            service.get_member_actions,
            member_id="me",
            filter="all",
            limit=page_size,
            before=before,
            since=since_iso,
        ) or []
        pages += 1
        if not page:
            break
        last_page_full = len(page) >= page_size
        for raw in page:
            if not isinstance(raw, dict):
                continue
            scanned += 1
            action_id = str(raw.get("id") or "")
            if not action_id or action_id in seen:
                continue
            seen.add(action_id)
            when = _action_datetime(raw.get("date"))
            if not when:
                continue
            if when.date() > until:
                continue
            if since and when.date() < since:
                reached_start = True
                continue
            if not _authored_by_member(raw, member):
                continue
            workspace = _workspace_context(
                raw, boards=boards, organizations=organizations
            )
            if not _workspace_allowed(workspace, selected):
                continue
            action_type = str(raw.get("type") or "").strip()
            data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
            if not action_type or not data:
                continue
            actions.append({
                "id": action_id,
                "type": action_type,
                "when": when.isoformat(),
                "when_dt": when,
                "data": data,
                "workspace": workspace,
                "references": _trello_references(
                    raw,
                    workspace=workspace,
                    username=str(member.get("username") or "brianbartilet"),
                ),
                "needs_synthesis": _needs_synthesis({
                    "type": action_type,
                    "data": data,
                }),
            })
            if len(actions) >= max_actions:
                break
        next_before = str(page[-1].get("id") or "")
        if (
            len(page) < page_size
            or not next_before
            or next_before == before
        ):
            break
        before = next_before

    actions.sort(key=lambda item: item["when_dt"])
    return {
        "actions": actions,
        "action_count": len(actions),
        "scanned": scanned,
        "pages": pages,
        "truncated": (
            len(actions) >= max_actions
            or (pages >= _MAX_MEMBER_PAGES and last_page_full)
        ),
        "member": {
            "id": member.get("id"),
            "username": member.get("username"),
        },
        "workspace_filter": sorted(selected) if selected else ["all"],
    }


@SPROUT.task()
@log_result()
def ingest_trello_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    period: str = "",
    since: str = "",
    until: str = "",
    window_days: int = 1,
    workspaces: Optional[str | list[str]] = None,
    page_size: int = 200,
    max_actions: int = 10_000,
    synthesize: bool = True,
) -> dict[str, Any]:
    """Ingest one HFL entry per authored Trello action."""
    if not _credentials_present():
        _log.info("ingest_trello: Trello credentials not configured — no-op")
        return {"skipped": "no credentials", "entries_written": 0, "actions": 0}
    try:
        start, end, label = resolve_trello_window(
            period=period,
            since=since,
            until=until,
            window_days=window_days,
        )
        collected = collect_trello_activity(
            since=start,
            until=end,
            service=ApiServiceTrelloMembers(TRELLO_CONFIG),
            workspaces=workspaces,
            page_size=page_size,
            max_actions=max_actions,
        )
    except Exception as exc:  # noqa: BLE001 - Trello must never break Beat
        _log.error("ingest_trello: Trello unavailable (%s)", exc)
        return {
            "skipped": "trello unavailable",
            "entries_written": 0,
            "actions": 0,
            "error": str(exc)[:300],
        }

    if collected["action_count"] == 0:
        _log.info("ingest_trello: no authored actions in %s", label)
        return {
            "skipped": "no actions",
            "entries_written": 0,
            "actions": 0,
            "period": label,
        }

    written = duplicates = distilled_skips = synthesized_count = 0
    deliveries: dict[str, int] = {}
    paths: set[str] = set()
    for action in collected["actions"]:
        distilled = distill_trello_activity(
            action,
            synthesize=bool(synthesize and action["needs_synthesis"]),
            model=model,
            cfg_id=cfg_id__anthropic,
            max_tokens=900,
        )
        if distilled.get("skip"):
            distilled_skips += 1
            continue
        base_tags = _format_action(action)["tags"]
        tags = tuple(dict.fromkeys([
            *base_tags,
            *[
                str(tag).strip().lstrip("#")
                for tag in (distilled.get("tags") or [])
                if str(tag).strip()
            ],
        ]))[:6]
        entry = HflEntry(
            when=action["when_dt"],
            moment=distilled["moment"],
            what_happened=distilled["what_happened"],
            why_it_stayed=distilled.get("why_it_stayed", ""),
            possible_use=distilled.get("possible_use") or "activity-log",
            tags=tags,
            references=tuple(action["references"]),
            source="trello",
        )
        result = submit_hfl_entry(
            entry,
            source="trello",
            synthesized=bool(distilled.get("synthesized")),
            dedup_key=f"trello:{action['id']}",
            es_doc_id=f"trello-action-{action['id']}",
        )
        delivery = str(result.get("delivery") or "unknown")
        deliveries[delivery] = deliveries.get(delivery, 0) + 1
        if result.get("duplicate"):
            duplicates += 1
        else:
            written += 1
        if result.get("path"):
            paths.add(str(result["path"]))
        synthesized_count += int(bool(distilled.get("synthesized")))

    return {
        "entries_written": written,
        "duplicates": duplicates,
        "distilled_skips": distilled_skips,
        "actions": collected["action_count"],
        "scanned": collected["scanned"],
        "pages": collected["pages"],
        "truncated": collected["truncated"],
        "synthesized": synthesized_count,
        "model": model if synthesized_count else None,
        "period": label,
        "workspace_filter": collected["workspace_filter"],
        "deliveries": deliveries,
        "paths": sorted(paths),
    }
