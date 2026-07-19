"""
workflows/hfl/tasks/ingest_chatgpt.py

Daily ChatGPT-web research → HFL corpus. Auto-discovers the operator's own
ChatGPT conversations created/updated that day, distils the questions they
asked into ONE Homework-for-Life entry, and appends it to the corpus so
the day's research flows into summarize_hfl_week + the memory_recall MCP.

Why this exists (and the caveats — read these):
  - OpenAI's *official* Platform API (apps/open_ai) cannot enumerate
    threads, and cannot see ChatGPT-app conversations at all. The only
    thing that can list "everything I chatted about today" is the ChatGPT
    web app's OWN private backend (chatgpt.com/backend-api), which the
    frontend uses. This task talks to that.
  - That backend is UNOFFICIAL and UNDOCUMENTED. Endpoint shapes can
    change with any web deploy and break this task silently (it degrades
    to a no-op / raw fallback, never to a broken beat).
  - Auth is a session-scoped bearer token, not an API key. Grab it from
    https://chatgpt.com/api/auth/session (the `accessToken` field) while
    logged in, and put it in CHATGPT_WEB_ACCESS_TOKEN. It EXPIRES (days)
    and must be re-pasted. Cloudflare bot protection may require a real
    browser's Cookie + User-Agent — see CHATGPT_WEB_COOKIE /
    CHATGPT_WEB_USER_AGENT below.
  - This is your own account and your own data for a personal log. That's
    the defensible case; automating the web backend is nonetheless a grey
    area vs. the sanctioned official API. You opted into this trade-off.

No token configured → no entry, no network call (clean no-op, mirrors
ingest_git_activity on a no-commit day). No prompts in the window →
no entry, no LLM call.

Config (env, resolved by deploy.py / .env/apps.env):
  CHATGPT_WEB_ACCESS_TOKEN  required — Bearer token from /api/auth/session
  CHATGPT_WEB_COOKIE        optional — raw Cookie header (e.g.
                            "cf_clearance=...; __Secure-next-auth.session-token=...")
                            to satisfy Cloudflare.
  CHATGPT_WEB_USER_AGENT    optional — overrides the default browser UA.
  CHATGPT_WEB_BASE_URL      optional — overrides the API base.

The collectors (collect_chatgpt_activity / distill_chatgpt_activity) are
plain functions so an MCP tool can reuse them for a live, no-write view.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_chatgpt")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

_DEFAULT_BASE = "https://chatgpt.com/backend-api"
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _coerce_dt(value: Any) -> Optional[datetime]:
    """ChatGPT timestamps are sometimes epoch floats, sometimes ISO strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError:
            return None
    return None


class _ChatGptWebClient:
    """Minimal client for the ChatGPT web app's private backend.

    Intentionally tiny and dependency-free (httpx only). Every call is
    best-effort: network/HTTP/JSON errors raise, and the task layer turns
    them into a clean skip rather than a broken beat.
    """

    def __init__(
        self,
        token: str,
        *,
        cookie: Optional[str] = None,
        user_agent: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self._base = (base_url or _DEFAULT_BASE).rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent or _DEFAULT_UA,
            "Accept": "*/*",
            "Content-Type": "application/json",
        }
        if cookie:
            headers["Cookie"] = cookie
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def __enter__(self) -> "_ChatGptWebClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001 - close must never raise
            pass

    def list_conversations(
        self, *, offset: int = 0, limit: int = 28, order: str = "updated"
    ) -> dict:
        r = self._client.get(
            f"{self._base}/conversations",
            params={"offset": offset, "limit": limit, "order": order},
        )
        r.raise_for_status()
        return r.json()

    def get_conversation(self, conversation_id: str) -> dict:
        r = self._client.get(f"{self._base}/conversation/{conversation_id}")
        r.raise_for_status()
        return r.json()


def _resolve_token() -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(token, cookie, user_agent, base_url) from env; token None → no-op."""
    token = os.environ.get("CHATGPT_WEB_ACCESS_TOKEN", "").strip() or None
    cookie = os.environ.get("CHATGPT_WEB_COOKIE", "").strip() or None
    ua = os.environ.get("CHATGPT_WEB_USER_AGENT", "").strip() or None
    base = os.environ.get("CHATGPT_WEB_BASE_URL", "").strip() or None
    return token, cookie, ua, base


def _extract_user_messages(detail: dict, *, since: date, until: date) -> list[dict]:
    """Pull the operator's (`author.role == "user"`) messages in [since, until].

    ChatGPT conversation detail is a `mapping` of node_id → node, each node
    optionally carrying a `message` with author/role, content.parts and a
    per-message create_time. We walk all nodes (order is reconstructed by
    timestamp — good enough for a daily digest) and keep user turns.
    """
    mapping = detail.get("mapping")
    if not isinstance(mapping, dict):
        return []
    out: list[dict] = []
    for node in mapping.values():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        role = (((msg.get("author") or {}).get("role")) or "").lower()
        if role != "user":
            continue
        when = _coerce_dt(msg.get("create_time"))
        if not when or not (since <= when.date() <= until):
            continue
        content = msg.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        text = ""
        if isinstance(parts, list):
            text = "\n".join(str(p).strip() for p in parts if p).strip()
        elif isinstance(content, str):
            text = content.strip()
        if not text:
            continue
        out.append({"when": when, "text": text[:2000]})
    out.sort(key=lambda m: m["when"])
    return [{"when": m["when"].strftime("%Y-%m-%d %H:%M"), "text": m["text"]} for m in out]


def collect_chatgpt_activity(
    *,
    since: date,
    until: date,
    client: _ChatGptWebClient,
    max_conversations: int = 40,
    page_size: int = 28,
    max_messages: int = 400,
) -> dict[str, Any]:
    """List conversations touched in [since, until], pull the operator's prompts.

    The list endpoint is `order=updated` (newest first), so we stop paging
    as soon as a conversation's update date falls before `since`.

    Returns:
        {"conversations": [{"id","title","messages":[{"when","text"}]}],
         "message_count", "conversation_count"}
    """
    groups: list[dict] = []
    total_msgs = 0
    seen_convos = 0
    offset = 0
    stop = False

    while not stop and seen_convos < max_conversations and total_msgs < max_messages:
        payload = client.list_conversations(offset=offset, limit=page_size)
        items = payload.get("items") or []
        if not items:
            break
        for it in items:
            if seen_convos >= max_conversations or total_msgs >= max_messages:
                break
            upd = _coerce_dt(it.get("update_time"))
            crt = _coerce_dt(it.get("create_time"))
            newest = max([d for d in (upd, crt) if d], default=None)
            if newest and newest.date() < since:
                stop = True  # updated-desc — nothing older can qualify
                break
            in_window = (
                (upd and since <= upd.date() <= until)
                or (crt and since <= crt.date() <= until)
            )
            if not in_window:
                continue
            cid = it.get("id")
            if not cid:
                continue
            seen_convos += 1
            try:
                detail = client.get_conversation(cid)
            except Exception as exc:  # noqa: BLE001 - skip a bad convo, keep going
                _log.info("ingest_chatgpt: get_conversation failed for %s (%s)", cid, exc)
                continue
            msgs = _extract_user_messages(detail, since=since, until=until)
            if not msgs:
                continue
            if total_msgs + len(msgs) > max_messages:
                msgs = msgs[: max_messages - total_msgs]
            groups.append({
                "id": cid,
                "title": (it.get("title") or "")[:160],
                "messages": msgs,
            })
            total_msgs += len(msgs)
        if stop or len(items) < page_size:
            break
        offset += page_size

    return {
        "conversations": groups,
        "message_count": total_msgs,
        "conversation_count": len(groups),
    }


def _activity_body(activity: dict) -> str:
    lines: list[str] = []
    for g in activity["conversations"]:
        title = g.get("title") or "(untitled)"
        lines.append(f"### {title} ({len(g['messages'])} prompts)")
        for m in g["messages"]:
            lines.append(f"- {m['when']}  {m['text']}")
    return "\n".join(lines)


def distill_chatgpt_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected prompts into HFL entry fields (Haiku, raw fallback)."""
    msg_count = activity["message_count"]
    convo_count = activity["conversation_count"]

    def _fallback() -> dict:
        bullets = []
        for g in activity["conversations"]:
            preview = "; ".join(m["text"][:80] for m in g["messages"][:6])
            title = g.get("title") or "(untitled)"
            bullets.append(f"- {title}: {len(g['messages'])} prompts — {preview}")
        return {
            "skip": False,
            "moment": f"{msg_count} ChatGPT prompt(s) across {convo_count} chat(s)",
            "what_happened": "\n".join(bullets),
            "why_it_stayed": "",
            "possible_use": "research-log",
            "tags": ["ai", "research", "chatgpt"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = (
        f"Operator prompts grouped by conversation ({msg_count} total across "
        f"{convo_count} chats):\n\n{_activity_body(activity)}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_chatgpt: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_chatgpt").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_chatgpt: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


@SPROUT.task()
@log_result()
def ingest_chatgpt_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_conversations: int = 40,
    page_size: int = 28,
    max_messages: int = 400,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's ChatGPT research.

    No CHATGPT_WEB_ACCESS_TOKEN configured → no entry, no network call.
    No operator prompts in the window → no entry, no LLM call.
    """
    token, cookie, ua, base = _resolve_token()
    if not token:
        _log.info("ingest_chatgpt: CHATGPT_WEB_ACCESS_TOKEN not set — no-op")
        return {"skipped": "no token", "entries_written": 0, "conversations": 0}

    until = datetime.now().date()
    since = until - timedelta(days=window_days)

    try:
        with _ChatGptWebClient(
            token, cookie=cookie, user_agent=ua, base_url=base
        ) as client:
            activity = collect_chatgpt_activity(
                since=since, until=until, client=client,
                max_conversations=max_conversations,
                page_size=page_size, max_messages=max_messages,
            )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        hint = " (token expired — re-grab from /api/auth/session)" if code == 401 else ""
        _log.error("ingest_chatgpt: ChatGPT web API HTTP %s%s", code, hint)
        return {"skipped": f"http {code}", "entries_written": 0,
                "error": f"HTTP {code}{hint}"}
    except Exception as exc:  # noqa: BLE001 - web backend down/changed must not break beat
        _log.error("ingest_chatgpt: ChatGPT web API unavailable (%s)", exc)
        return {"skipped": "chatgpt unavailable", "entries_written": 0,
                "error": str(exc)[:200]}

    if activity["message_count"] == 0:
        _log.info("ingest_chatgpt: no prompts in last %d day(s)", window_days)
        return {"skipped": "no prompts", "entries_written": 0, "conversations": 0}

    d = distill_chatgpt_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info("ingest_chatgpt: distilled as skip — %d prompts not story-worthy",
                  activity["message_count"])
        return {"skipped": "distilled-skip", "entries_written": 0,
                "message_count": activity["message_count"]}

    tags = ["ai", "research", "chatgpt"] + [
        str(t) for t in (d.get("tags") or []) if str(t).strip()
    ][:6]

    when = datetime.now()
    entry = HflEntry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "research-log",
        tags=tags,
    )
    persistence = submit_hfl_entry(
        entry,
        source="chatgpt",
        synthesized=d.get("synthesized", False),
    )

    _log.info(
        "ingest_chatgpt: entry %s (%d prompts, %d chats)",
        persistence.get("delivery"),
        activity["message_count"],
        activity["conversation_count"],
    )
    return {
        "entries_written": 1,
        "conversations": activity["conversation_count"],
        "prompts": activity["message_count"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": persistence.get("path", ""),
        "delivery": persistence.get("delivery"),
        "entry_id": persistence.get("entry_id"),
    }
