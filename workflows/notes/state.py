"""Atomic host-local pull status and HFL cursor state for note repositories."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workflows.notes.config import get_notes_state_dir


def _state_path(kind: str, repository: str, cfg: dict | None = None) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in repository)
    return get_notes_state_dir(cfg) / kind / f"{safe}.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def record_pull_status(
    repository: str,
    *,
    success: bool,
    head: str = "",
    detail: str = "",
    cfg: dict | None = None,
) -> None:
    _write(_state_path("pull", repository, cfg), {
        "repository": repository,
        "success": bool(success),
        "head": head,
        "detail": detail[:300],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def recent_pull_succeeded(
    repository: str,
    *,
    head: str,
    max_age_minutes: int = 90,
    cfg: dict | None = None,
) -> bool:
    data = _read(_state_path("pull", repository, cfg))
    if not data.get("success") or data.get("head") != head:
        return False
    try:
        when = datetime.fromisoformat(str(data["updated_at"]).replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - when.astimezone(timezone.utc)
        return age.total_seconds() <= max(1, max_age_minutes) * 60
    except (KeyError, TypeError, ValueError):
        return False


def load_ingest_cursor(repository: str, cfg: dict | None = None) -> str | None:
    value = _read(_state_path("cursor", repository, cfg)).get("commit")
    return str(value).strip() if value else None


def store_ingest_cursor(repository: str, commit: str, cfg: dict | None = None) -> None:
    _write(_state_path("cursor", repository, cfg), {
        "repository": repository,
        "commit": commit,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
