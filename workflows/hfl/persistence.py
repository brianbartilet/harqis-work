"""Canonical HFL persistence, provenance, deduplication, and outbox delivery."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from filelock import FileLock

from workflows.hfl.dto import HflEntry


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTBOX = REPO_ROOT / "logs" / "hfl-outbox"
CANONICAL_MACHINE = "harqis-server"
_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def local_machine_name() -> str:
    """Resolve the configured machine name, with hostname as a safe fallback."""
    try:
        from workflows.dumps.config import resolve_local_machine_name

        return resolve_local_machine_name()
    except Exception:
        return socket.gethostname() or "unknown"


def is_canonical_machine(machine: str | None = None) -> bool:
    return (machine or local_machine_name()).casefold() == CANONICAL_MACHINE.casefold()


def outbox_dir() -> Path:
    configured = os.environ.get("HFL_OUTBOX_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_OUTBOX


def deterministic_entry_id(
    entry: HflEntry,
    *,
    source: str,
    machine: str,
    dedup_key: str | None = None,
) -> str:
    """Return a stable delivery id for at-least-once Celery semantics."""
    identity: dict[str, Any] = {
        "version": 1,
        "source": source.strip().casefold(),
        "machine": machine.strip().casefold(),
    }
    if dedup_key:
        identity["dedup_key"] = str(dedup_key).strip()
    else:
        identity.update({
            "when": entry.when.strftime("%Y-%m-%dT%H:%M") if entry.when else "",
            "moment": entry.moment,
            "what_happened": entry.what_happened,
            "why_it_stayed": entry.why_it_stayed,
            "possible_use": entry.possible_use,
            "tags": list(entry.tags),
            "references": list(entry.references),
        })
    encoded = json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "hfl-" + hashlib.sha256(encoded).hexdigest()[:24]


@dataclass(frozen=True)
class EntryEnvelope:
    entry: HflEntry
    synthesized: bool = False
    es_doc_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "entry": {
                "when": self.entry.when.isoformat() if self.entry.when else None,
                "moment": self.entry.moment,
                "what_happened": self.entry.what_happened,
                "why_it_stayed": self.entry.why_it_stayed,
                "possible_use": self.entry.possible_use,
                "tags": list(self.entry.tags),
                "references": list(self.entry.references),
                "source": self.entry.source,
                "machine": self.entry.machine,
                "entry_id": self.entry.entry_id,
            },
            "synthesized": self.synthesized,
            "es_doc_id": self.es_doc_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EntryEnvelope":
        raw = payload.get("entry") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raise ValueError("missing entry payload")
        when_raw = raw.get("when")
        when = datetime.fromisoformat(str(when_raw)) if when_raw else None
        entry = HflEntry(
            when=when,
            moment=str(raw.get("moment") or ""),
            what_happened=str(raw.get("what_happened") or ""),
            why_it_stayed=str(raw.get("why_it_stayed") or ""),
            possible_use=str(raw.get("possible_use") or ""),
            tags=tuple(str(tag) for tag in (raw.get("tags") or [])),
            references=tuple(str(ref) for ref in (raw.get("references") or [])),
            source=str(raw.get("source") or ""),
            machine=str(raw.get("machine") or ""),
            entry_id=str(raw.get("entry_id") or ""),
        )
        if not entry.moment or not entry.source or not entry.machine or not entry.entry_id:
            raise ValueError("entry payload is missing required canonical metadata")
        return cls(
            entry=entry,
            synthesized=bool(payload.get("synthesized")),
            es_doc_id=str(payload.get("es_doc_id") or "") or None,
        )


def make_envelope(
    entry: HflEntry,
    *,
    source: str,
    synthesized: bool = False,
    machine: str | None = None,
    dedup_key: str | None = None,
    es_doc_id: str | None = None,
) -> EntryEnvelope:
    origin = (machine or local_machine_name()).strip() or "unknown"
    source_name = (source or "unknown").strip() or "unknown"
    entry_id = deterministic_entry_id(
        entry,
        source=source_name,
        machine=origin,
        dedup_key=dedup_key,
    )
    enriched = replace(
        entry,
        source=source_name,
        machine=origin,
        entry_id=entry_id,
    )
    return EntryEnvelope(enriched, bool(synthesized), es_doc_id)


def _entry_blocks(text: str) -> Iterable[HflEntry]:
    matches = list(_HEADER.finditer(text or ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        yield HflEntry.from_markdown(match.group(1), text[match.end():end])


def _content_signature(entry: HflEntry) -> tuple[Any, ...]:
    return (
        entry.when.strftime("%Y-%m-%dT%H:%M") if entry.when else "",
        entry.moment,
        entry.what_happened,
        entry.why_it_stayed,
        entry.possible_use,
        tuple(entry.tags),
        tuple(entry.references),
    )


def persist_envelope(
    envelope: EntryEnvelope,
    *,
    corpus_dir: Path | None = None,
) -> dict[str, Any]:
    """Prepend exactly once under a per-day cross-process file lock."""
    entry = envelope.entry
    if not entry.when:
        raise ValueError("canonical HFL entries require a timestamp")
    if not entry.moment:
        raise ValueError("canonical HFL entries require a moment")
    if corpus_dir is None:
        from workflows.hfl.tasks.capture import resolve_corpus_dir

        corpus_dir = resolve_corpus_dir()
    corpus_dir = Path(corpus_dir).expanduser().resolve()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{entry.when:%Y-%m-%d}.md"
    duplicate = False
    rendered = entry.to_markdown()

    with FileLock(str(day_file) + ".lock", timeout=30):
        existing_text = day_file.read_text(encoding="utf-8") if day_file.exists() else ""
        existing_entries = tuple(_entry_blocks(existing_text))
        duplicate = any(
            existing.entry_id == entry.entry_id
            or _content_signature(existing) == _content_signature(entry)
            for existing in existing_entries
        )
        if not duplicate:
            temporary = day_file.with_name(
                f".{day_file.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
            )
            try:
                with temporary.open("w", encoding="utf-8") as handle:
                    written = handle.write(rendered)
                    handle.write(existing_text)
                    handle.flush()
                    os.fsync(handle.fileno())
                if day_file.exists():
                    os.chmod(temporary, day_file.stat().st_mode)
                os.replace(temporary, day_file)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            written = 0

    from workflows.hfl.es_store import index_hfl_entry

    doc_id = index_hfl_entry(
        entry,
        source=entry.source,
        synthesized=envelope.synthesized,
        doc_id=envelope.es_doc_id or entry.entry_id,
    )
    return {
        "entry_id": entry.entry_id,
        "path": str(day_file),
        "bytes_written": written,
        "duplicate": duplicate,
        "indexed": doc_id is not None,
        "doc_id": doc_id,
        "delivery": "persisted",
    }


def _outbox_path(envelope: EntryEnvelope) -> Path:
    return outbox_dir() / f"{envelope.entry.entry_id}.json"


def save_to_outbox(envelope: EntryEnvelope) -> Path:
    target = _outbox_path(envelope)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(envelope.to_payload(), handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return target


def remove_from_outbox(envelope: EntryEnvelope) -> None:
    _outbox_path(envelope).unlink(missing_ok=True)


def load_outbox(path: Path) -> EntryEnvelope:
    return EntryEnvelope.from_payload(json.loads(path.read_text(encoding="utf-8")))


def _dispatch(envelope: EntryEnvelope) -> str:
    from core.apps.sprout.app.celery import SPROUT
    from workflows.queues import WorkflowQueue

    result = SPROUT.send_task(
        "workflows.hfl.tasks.persist.persist_hfl_entry",
        kwargs={"payload": envelope.to_payload()},
        queue=WorkflowQueue.HFL.value,
    )
    return str(result.id)


def submit_hfl_entry(
    entry: HflEntry,
    *,
    source: str,
    synthesized: bool = False,
    dedup_key: str | None = None,
    es_doc_id: str | None = None,
) -> dict[str, Any]:
    """Durably submit an entry locally or to the canonical HFL queue."""
    envelope = make_envelope(
        entry,
        source=source,
        synthesized=synthesized,
        dedup_key=dedup_key,
        es_doc_id=es_doc_id,
    )
    path = save_to_outbox(envelope)
    try:
        if is_canonical_machine():
            result = persist_envelope(envelope)
        else:
            result = {
                "entry_id": envelope.entry.entry_id,
                "task_id": _dispatch(envelope),
                "path": "",
                "bytes_written": 0,
                "duplicate": False,
                "indexed": None,
                "doc_id": envelope.es_doc_id,
                "delivery": "forwarded",
            }
        remove_from_outbox(envelope)
        return result
    except Exception as exc:
        return {
            "entry_id": envelope.entry.entry_id,
            "path": "",
            "bytes_written": 0,
            "duplicate": False,
            "indexed": None,
            "doc_id": envelope.es_doc_id,
            "delivery": "outbox",
            "outbox": str(path),
            "error": type(exc).__name__,
        }


def flush_outbox(*, limit: int = 100) -> dict[str, int]:
    root = outbox_dir()
    counts = {"found": 0, "delivered": 0, "failed": 0, "invalid": 0}
    if not root.exists():
        return counts
    for path in sorted(root.glob("*.json"))[:max(1, int(limit))]:
        counts["found"] += 1
        try:
            envelope = load_outbox(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            counts["invalid"] += 1
            continue
        try:
            if is_canonical_machine():
                persist_envelope(envelope)
            else:
                _dispatch(envelope)
            path.unlink(missing_ok=True)
            counts["delivered"] += 1
        except Exception:
            counts["failed"] += 1
    return counts
