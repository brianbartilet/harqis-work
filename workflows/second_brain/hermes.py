"""Bounded, optional Hermes interpretation behind a strict JSON contract."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from workflows.second_brain.models import normalize_modes
from workflows.second_brain.prompts import load_prompt


class HermesUnavailable(RuntimeError):
    pass


def _response_content(payload: Any) -> str:
    try:
        value = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HermesUnavailable("Hermes returned an invalid response") from None
    if not isinstance(value, str) or not value.strip():
        raise HermesUnavailable("Hermes returned an empty response")
    return value.strip()


def interpret_context(events: list[dict[str, Any]], modes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a validated mode candidate or raise without affecting fallback."""
    base_url = os.environ.get("SECOND_BRAIN_HERMES_BASE_URL", "http://127.0.0.1:8643/v1").rstrip("/")
    api_key = os.environ.get("SECOND_BRAIN_HERMES_API_KEY", "").strip()
    model = os.environ.get("SECOND_BRAIN_HERMES_MODEL", "second-brain").strip()
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
        or not api_key
        or not model
    ):
        raise HermesUnavailable("Hermes must be a configured loopback profile")
    safe_events = []
    for event in events[:30]:
        safe_events.append(
            {
                "source": str(event.get("source") or "")[:80],
                "event_type": str(event.get("event_type") or "")[:80],
                "observed_at": str(event.get("observed_at") or "")[:80],
                "payload": {
                    str(key)[:80]: str(value)[:500]
                    for key, value in (event.get("payload") or {}).items()
                },
            }
        )
    session_id = f"second-brain-{uuid.uuid4().hex}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Hermes-Session-Id": session_id,
    }
    cleanup_url = f"{parsed.scheme}://{parsed.netloc}/api/sessions/{quote(session_id, safe='')}"
    try:
        response = httpx.post(
            base_url + "/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": load_prompt("context_interpreter")},
                    {"role": "user", "content": json.dumps({"available_modes": modes or [], "events": safe_events}, ensure_ascii=False)},
                ],
                "max_tokens": 240,
                "stream": False,
            },
            timeout=15,
            follow_redirects=False,
            trust_env=False,
        )
        response.raise_for_status()
    finally:
        try:
            httpx.delete(
                cleanup_url,
                headers={"Authorization": headers["Authorization"]},
                timeout=5,
                follow_redirects=False,
                trust_env=False,
            )
        except Exception:
            pass
    try:
        candidate = json.loads(_response_content(response.json()))
        modes = normalize_modes(candidate.get("modes") or ())
        confidence = max(0.0, min(1.0, float(candidate.get("confidence", 0))))
        reasons = tuple(str(reason)[:80] for reason in (candidate.get("reason_codes") or [])[:3])
    except (json.JSONDecodeError, TypeError, ValueError):
        raise HermesUnavailable("Hermes returned an invalid decision") from None
    if not modes:
        raise HermesUnavailable("Hermes returned no modes")
    return {"modes": list(modes), "confidence": confidence, "reason_codes": list(reasons), "model": model}


def chat_with_feed(*, question: str, history: list[dict[str, Any]], feed_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a bounded advisory answer grounded only in the supplied feed."""
    base_url = os.environ.get("SECOND_BRAIN_HERMES_BASE_URL", "http://127.0.0.1:8643/v1").rstrip("/")
    api_key = os.environ.get("SECOND_BRAIN_HERMES_API_KEY", "").strip()
    model = os.environ.get("SECOND_BRAIN_HERMES_MODEL", "second-brain").strip()
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"} or parsed.path.rstrip("/") != "/v1" or not api_key:
        raise HermesUnavailable("Hermes must be a configured loopback profile")
    evidence = [
        {
            "ref": str(item.get("logical_key") or "")[:160],
            "title": str(item.get("title") or "")[:240],
            "summary": str(item.get("summary") or "")[:600],
            "category": str(item.get("category") or "")[:48],
        }
        for item in feed_items[:20]
    ]
    messages = [{"role": "system", "content": "You are the advisory HARQIS Second Brain. Answer from the supplied feed evidence, cite logical refs in brackets, and never claim to perform actions."}]
    messages.extend({"role": row["role"], "content": str(row["content"])[:4000]} for row in history[-12:])
    messages.append({"role": "user", "content": json.dumps({"question": question[:2000], "feed": evidence}, ensure_ascii=False)})
    response = httpx.post(
        base_url + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages, "max_tokens": 900, "stream": False},
        timeout=45,
        follow_redirects=False,
        trust_env=False,
    )
    response.raise_for_status()
    answer = _response_content(response.json())
    citations = [item["ref"] for item in evidence if f"[{item['ref']}]" in answer]
    return {"answer": answer, "citations": citations, "model": model}
