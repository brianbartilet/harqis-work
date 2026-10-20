"""Essential Space Markdown exports -> one durable HFL entry per capture revision.

NOTHING_ESSENTIAL_SPACE_EXPORT_DIR is an operator-managed, retained export inbox.
Optional <name>.metadata.json sidecars follow our schema, NOT a Nothing API schema.
No configuration/items -> no model call or corpus write. MCP acquisition is an
explicit unimplemented backend pending verified authentication and tool schemas.
The plain collector powers the read-only HARQIS MCP preview.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from filelock import FileLock

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger
from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from workflows.hfl.distill import parse_model_json
from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry, outbox_dir
from workflows.hfl.prompts import load_prompt

_log = create_logger("hfl.ingest_nothing_essential_space")
_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
SOURCE = "nothing-essential-space"
MAX_FILE_BYTES = 1_000_000


class CaptureBackend(Protocol):
    """Future authenticated MCP adapter must return this collector contract."""

    def collect(self, *, since: date, until: date, max_captures: int,
                max_scan: int, exclude_keys: set[str]) -> dict: ...


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("file exceeds size limit")
    return raw


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("reference escapes export inbox")
    return resolved


class ExportFolderBackend:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def collect(self, *, since: date, until: date, max_captures: int,
                max_scan: int, exclude_keys: set[str]) -> dict:
        if not self.root.is_dir():
            raise ValueError("export inbox is not a directory")
        captures, errors, seen = [], [], set(exclude_keys)
        scanned, truncated = 0, False
        # Deliberately flat: no traversal into unrelated synced folders.
        for path in self.root.iterdir():
            if scanned >= max_scan:
                truncated = True
                break
            scanned += 1
            if path.suffix.lower() != ".md":
                continue
            try:
                path = _inside(self.root, path)
                raw = _read_bounded(path, MAX_FILE_BYTES)
                body = raw.decode("utf-8-sig").strip()
                if not body:
                    continue
                sidecar = path.with_suffix(".metadata.json")
                metadata = {}
                if sidecar.exists():
                    metadata = json.loads(_read_bounded(
                        _inside(self.root, sidecar), 64_000).decode("utf-8"))
                    if not isinstance(metadata, dict):
                        raise ValueError("metadata must be an object")
                captured_at = metadata.get("captured_at")
                # Preserve wall time/offset when provided; never call mtime capture time.
                when = (datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
                        if captured_at else datetime.fromtimestamp(path.stat().st_mtime))
                if not since <= when.date() <= until:
                    continue
                attachments = metadata.get("attachments", [])
                if not isinstance(attachments, list) or len(attachments) > 20:
                    raise ValueError("attachments must be a list of at most 20 paths")
                refs = [str(path)]
                if sidecar.exists():
                    refs.append(str(sidecar))
                for name in attachments:
                    if not isinstance(name, str) or Path(name).is_absolute():
                        raise ValueError("attachment must be a relative inbox path")
                    attachment = _inside(self.root, self.root / name)
                    if not attachment.is_file():
                        raise ValueError("attachment is missing")
                    refs.append(str(attachment))
                # Content + metadata revision, independent of export filename/mtime.
                digest = hashlib.sha256(
                    raw + b"\0" + json.dumps(metadata, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if digest in seen:
                    continue
                if len(captures) >= max_captures:
                    truncated = True
                    break
                seen.add(digest)
                title = str(metadata.get("title") or next(
                    (line.lstrip("# ").strip() for line in body.splitlines()
                     if line.startswith("# ")), path.stem))[:160]
                captures.append({
                    "key": digest, "capture_id": metadata.get("capture_id"),
                    "title": title, "when": when.isoformat(),
                    "timestamp_basis": "captured_at" if captured_at else "export_mtime",
                    "export_text": body, "references": refs,
                })
            except (OSError, ValueError, TypeError) as exc:
                # Do not put private content or parser exception text into logs.
                errors.append({"file": path.name, "error": type(exc).__name__})
        return {"captures": captures, "count": len(captures), "errors": errors,
                "scanned": scanned, "truncated": truncated, "backend": "export"}


def collect_nothing_essential_space_activity(
    *, since: date, until: date, max_captures: int = 25, max_scan: int = 5000,
    exclude_keys: set[str] | None = None, backend: CaptureBackend | None = None,
) -> dict:
    """Read-only, bounded preview; no network, receipts, or model calls."""
    if since > until:
        raise ValueError("since must not be after until")
    if not 1 <= max_captures <= 100 or not 1 <= max_scan <= 100_000:
        raise ValueError("caps outside supported bounds")
    if backend is None:
        mode = os.environ.get("NOTHING_ESSENTIAL_SPACE_BACKEND", "export").strip()
        if mode == "mcp":
            raise NotImplementedError("Nothing MCP acquisition awaits verified schemas")
        if mode != "export":
            raise ValueError("unsupported Essential Space backend")
        root = os.environ.get("NOTHING_ESSENTIAL_SPACE_EXPORT_DIR", "").strip()
        if not root:
            return {"captures": [], "count": 0, "skipped": "no export inbox",
                    "errors": [], "truncated": False, "backend": "export"}
        backend = ExportFolderBackend(Path(root))
    return backend.collect(since=since, until=until, max_captures=max_captures,
                           max_scan=max_scan, exclude_keys=exclude_keys or set())


def distill_nothing_essential_space_activity(
    activity: dict, *, synthesize: bool = True, model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC", max_tokens: int = 900,
) -> dict:
    """Distil ONE capture, explicitly labelling unstructured export evidence."""
    fallback = {
        "skip": False, "moment": activity["title"],
        "what_happened": "Essential Space export (may contain an AI summary):\n"
                         + activity["export_text"][:24_000],
        "why_it_stayed": "", "possible_use": "capture-log",
        "tags": ["nothing", "essential-space"], "synthesized": False,
    }
    if not synthesize:
        return fallback
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return fallback
        response = client.send_message(
            prompt=json.dumps({"title": activity["title"],
                               "export_text": activity["export_text"][:24_000]}),
            system=load_prompt("ingest_nothing_essential_space"),
            model=model, max_tokens=max_tokens,
        )
        parsed = parse_model_json(response.content[0].text)
        if not isinstance(parsed.get("skip"), bool):
            return fallback
        if parsed["skip"]:
            return {"skip": True, "synthesized": True}
        fields = ("moment", "what_happened", "why_it_stayed", "possible_use")
        if not all(isinstance(parsed.get(key), str) for key in fields):
            return fallback
        if not parsed["moment"].strip() or not parsed["what_happened"].strip():
            return fallback
        if not isinstance(parsed.get("tags"), list):
            return fallback
        return {**{key: parsed[key].strip() for key in fields},
                "skip": False, "synthesized": True,
                "tags": [tag.strip().lstrip("#") for tag in parsed["tags"]
                         if isinstance(tag, str) and tag.strip()][:6]}
    except Exception as exc:
        _log.warning("Essential Space synthesis failed: %s", type(exc).__name__)
        return fallback


def _ingest(*, cfg_id__anthropic="ANTHROPIC", model=_DEFAULT_HAIKU,
            window_days=7, max_captures=25, max_scan=5000, synthesize=False,
            since="", until="") -> dict:
    """Internal runner; task decorator owns operational logging."""
    result = {"entries_written": 0, "entries_submitted": 0, "outcomes": [],
              "errors": [], "skipped_count": 0}
    try:
        end = date.fromisoformat(until) if until else datetime.now().date()
        if not 1 <= window_days <= 3650:
            raise ValueError("window_days outside supported bounds")
        start = date.fromisoformat(since) if since else end - timedelta(days=window_days - 1)
        if (os.environ.get("NOTHING_ESSENTIAL_SPACE_BACKEND", "export") == "export"
                and not os.environ.get("NOTHING_ESSENTIAL_SPACE_EXPORT_DIR", "").strip()):
            return {**result, "skipped": "no export inbox"}
        state = outbox_dir().parent / "nothing-essential-space"
        state.mkdir(parents=True, exist_ok=True)
        with FileLock(str(state / "ingest.lock"), timeout=1):
            completed = {p.stem for p in state.glob("*.done")}
            activity = collect_nothing_essential_space_activity(
                since=start, until=end, max_captures=max_captures,
                max_scan=max_scan, exclude_keys=completed)
            result.update(errors=activity["errors"], truncated=activity["truncated"],
                          captures_found=activity["count"])
            for capture in activity["captures"]:
                try:
                    distilled = distill_nothing_essential_space_activity(
                        capture, synthesize=synthesize, model=model, cfg_id=cfg_id__anthropic)
                    if distilled["skip"]:
                        result["skipped_count"] += 1
                        receipt = {"delivery": "distilled-skip"}
                    else:
                        entry = HflEntry(
                            when=datetime.fromisoformat(capture["when"]),
                            moment=distilled["moment"],
                            what_happened=distilled["what_happened"] +
                            f"\nTimestamp basis: {capture['timestamp_basis']}.",
                            why_it_stayed=distilled["why_it_stayed"],
                            possible_use=distilled["possible_use"],
                            tags=tuple(distilled["tags"]),
                            references=tuple(capture["references"]),
                        )
                        receipt = submit_hfl_entry(
                            entry, source=SOURCE, synthesized=distilled["synthesized"],
                            dedup_key=f"export-v1:{capture['key']}")
                        if receipt.get("delivery") not in {"persisted", "forwarded", "outbox"}:
                            raise ValueError("unrecognised persistence acknowledgement")
                        result["entries_submitted"] += 1
                        result["entries_written"] += int(
                            receipt["delivery"] == "persisted" and not receipt.get("duplicate"))
                        result["outcomes"].append(receipt)
                    temporary = state / f"{capture['key']}.tmp"
                    temporary.write_text(json.dumps(receipt), encoding="utf-8")
                    temporary.replace(state / f"{capture['key']}.done")
                except Exception as exc:
                    result["errors"].append({"key": capture["key"],
                                             "error": type(exc).__name__})
            if not activity["count"]:
                result["skipped"] = "no new captures in window"
    except Exception as exc:
        result["skipped"] = "source unavailable"
        result["errors"].append({"error": type(exc).__name__})
        _log.warning("Essential Space ingestion unavailable: %s", type(exc).__name__)
    return result


@SPROUT.task()
@log_result()
def ingest_nothing_essential_space_activity(
    *, cfg_id__anthropic: str = "ANTHROPIC", model: str = _DEFAULT_HAIKU,
    window_days: int = 7, max_captures: int = 25, max_scan: int = 5000,
    synthesize: bool = False, since: str = "", until: str = "",
) -> dict:
    """Durably submit captures; synthesis is opt-in, scheduling ships disabled."""
    return _ingest(cfg_id__anthropic=cfg_id__anthropic, model=model,
                   window_days=window_days, max_captures=max_captures,
                   max_scan=max_scan, synthesize=synthesize, since=since, until=until)
