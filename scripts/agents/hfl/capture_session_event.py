#!/usr/bin/env python3
"""Capture agent prompt/outcome pairs into a sanitized HFL audit spool.

The script is deliberately stdlib-only on its write path so Codex/Claude hooks
can capture even when HARQIS services are unavailable.  With ``--enqueue`` it
also makes a best-effort Celery submission; failures leave the local event in
place for retry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO_ROOT / "logs" / "hfl-session-audit"
SURFACES = {"codex", "claude-code", "hermes", "openclaw"}

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs]|AIza)[-_A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{12,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [^-]+ PRIVATE KEY-----.*?-----END [^-]+ PRIVATE KEY-----", re.DOTALL),
)
_URL_CREDENTIAL_RE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://[^\s:/]+:)[^\s@/]+(@)"
)


def sanitize_text(value: Any, *, limit: int = 50_000) -> str:
    text = str(value or "").replace("\x00", "")[:limit]
    text = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]\2", text)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text.strip()


def _clean_id(value: Any, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "")).strip("-.")
    return cleaned[:160] or fallback


def audit_root() -> Path:
    configured = os.environ.get("HFL_SESSION_AUDIT_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ROOT


def _timestamp(value: Any = None) -> str:
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().isoformat()
        except ValueError:
            pass
    return datetime.now().astimezone().isoformat()


def _event_id(surface: str, session_id: str, prompt_id: str, prompt: str) -> str:
    raw = json.dumps(
        [surface, session_id, prompt_id, prompt], ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "agent-" + hashlib.sha256(raw).hexdigest()[:24]


def extract_artifacts(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    patterns = (
        ("url", r"https?://[^\s)>\]]+"),
        ("commit", r"(?<![A-Fa-f0-9])(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{7,12})(?![A-Fa-f0-9])"),
        ("file", r"(?:[A-Za-z]:\\|/)[^\n\r`<>|]+?\.[A-Za-z0-9]{1,8}(?=$|[\s):,])"),
    )
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            value = match.group(0).rstrip(".,;'")
            if value not in seen:
                seen.add(value)
                found.append({"kind": kind, "value": value[:1000]})
            if len(found) >= 50:
                return found
    return found


def normalize_event(raw: dict[str, Any], *, surface: str | None = None) -> dict[str, Any]:
    chosen_surface = _clean_id(surface or raw.get("surface"), "unknown").lower()
    if chosen_surface not in SURFACES:
        chosen_surface = "unknown"
    session_id = _clean_id(raw.get("session_id"), "session-unknown")
    prompt_id = _clean_id(raw.get("prompt_id") or raw.get("turn_id"), "prompt-unknown")
    prompt = sanitize_text(raw.get("original_prompt") or raw.get("prompt"))
    outcome = sanitize_text(raw.get("assistant_outcome") or raw.get("outcome"))
    happened_at = _timestamp(raw.get("timestamp") or raw.get("prompt_timestamp"))
    event_id = _clean_id(raw.get("event_id"), "") or _event_id(
        chosen_surface, session_id, prompt_id, prompt
    )
    supplied = raw.get("artifacts") if isinstance(raw.get("artifacts"), list) else []
    artifacts = extract_artifacts(outcome)
    for item in supplied:
        if not isinstance(item, dict):
            continue
        value = sanitize_text(item.get("value"), limit=1000)
        if value and not any(existing["value"] == value for existing in artifacts):
            artifacts.append({"kind": _clean_id(item.get("kind"), "artifact"), "value": value})
    return {
        "schema_version": 1,
        "event_id": event_id,
        "surface": chosen_surface,
        "session_id": session_id,
        "prompt_id": prompt_id,
        "timestamp": happened_at,
        "captured_at": datetime.now().astimezone().isoformat(),
        "original_prompt": prompt,
        "corrected_prompt": sanitize_text(raw.get("corrected_prompt")),
        "request_summary": sanitize_text(raw.get("request_summary"), limit=5000),
        "assistant_outcome": outcome,
        "work_summary": sanitize_text(raw.get("work_summary"), limit=10_000),
        "result_status": _clean_id(raw.get("result_status") or raw.get("status"), "completed").lower(),
        "artifacts": artifacts[:50],
        "tags": [sanitize_text(tag, limit=100).lstrip("#") for tag in raw.get("tags", []) if sanitize_text(tag, limit=100)],
        "machine": _clean_id(raw.get("machine") or socket.gethostname(), "unknown"),
        "ingest": raw.get("ingest") if isinstance(raw.get("ingest"), dict) else {},
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_event(event: dict[str, Any]) -> Path:
    day = datetime.fromisoformat(event["timestamp"]).strftime("%Y-%m-%d")
    path = audit_root() / "events" / day / f"{event['event_id']}.json"
    _atomic_json(path, event)
    return path


def _pending_path(surface: str, session_id: str) -> Path:
    return audit_root() / "pending" / surface / f"{_clean_id(session_id, 'session-unknown')}.json"


def capture_hook(payload: dict[str, Any], surface: str) -> tuple[dict[str, Any] | None, Path | None]:
    event_name = str(payload.get("hook_event_name") or "").lower()
    session_id = _clean_id(payload.get("session_id"), "session-unknown")
    pending_path = _pending_path(surface, session_id)
    if event_name == "userpromptsubmit":
        pending = {
            "surface": surface,
            "session_id": session_id,
            "prompt_id": payload.get("turn_id") or payload.get("prompt_id"),
            "timestamp": payload.get("timestamp"),
            "original_prompt": payload.get("prompt") or payload.get("user_prompt") or "",
            "machine": socket.gethostname(),
        }
        _atomic_json(pending_path, normalize_event(pending, surface=surface))
        return None, pending_path
    if event_name not in {"stop", "sessionend"}:
        return None, None
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pending = {}
    outcome = payload.get("last_assistant_message") or payload.get("assistant_response") or payload.get("outcome") or ""
    if not pending.get("original_prompt") or not outcome:
        return None, None
    pending.update({
        "assistant_outcome": outcome,
        "result_status": payload.get("result_status") or "completed",
        "artifacts": payload.get("artifacts") or [],
    })
    event = normalize_event(pending, surface=surface)
    path = write_event(event)
    pending_path.unlink(missing_ok=True)
    return event, path


def enqueue_event(event: dict[str, Any], artifact_path: Path) -> str | None:
    try:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import launch  # type: ignore

        launch.setup_env()
        from core.apps.sprout.app.celery import SPROUT
        from workflows.queues import WorkflowQueue

        result = SPROUT.send_task(
            "workflows.hfl.tasks.ingest_agent_sessions.ingest_agent_session_event",
            kwargs={"payload": event, "source_artifact": str(artifact_path)},
            queue=WorkflowQueue.HFL.value,
        )
        return str(result.id)
    except Exception:
        return None


def _load_json_arg(value: str) -> dict[str, Any]:
    if value == "-":
        return json.load(sys.stdin)
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, choices=sorted(SURFACES))
    parser.add_argument("--hook", action="store_true", help="read a lifecycle-hook payload from stdin")
    parser.add_argument("--json", help="common envelope as JSON, path, or '-' for stdin")
    parser.add_argument("--prompt")
    parser.add_argument("--outcome")
    parser.add_argument("--session-id")
    parser.add_argument("--prompt-id")
    parser.add_argument("--status", default="completed")
    parser.add_argument("--enqueue", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)

    if args.hook:
        payload = json.load(sys.stdin)
        event, path = capture_hook(payload, args.surface)
        if event is None or path is None:
            return 0
    else:
        raw = _load_json_arg(args.json) if args.json else {
            "original_prompt": args.prompt,
            "assistant_outcome": args.outcome,
            "session_id": args.session_id,
            "prompt_id": args.prompt_id,
            "result_status": args.status,
        }
        event = normalize_event(raw, surface=args.surface)
        if not event["original_prompt"] or not event["assistant_outcome"]:
            parser.error("both prompt and assistant outcome are required")
        path = write_event(event)

    task_id = enqueue_event(event, path) if args.enqueue else None
    print(json.dumps({"captured": True, "event_id": event["event_id"], "path": str(path), "task_id": task_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
