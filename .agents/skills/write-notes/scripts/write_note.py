"""Validate and submit structured notes to the HFL Corpus API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTBOX = REPO_ROOT / "logs" / "write-notes-outbox"
MAX_FILES = 10
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
DEFAULT_OCR_MAX_CHARS = 12_000
SUPPORTED_IMAGE_SUFFIXES = {
    ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
}
_TAG_TOKEN = re.compile(r"[^\w-]+", re.UNICODE)
_MARKDOWN_LINK = re.compile(r"^\[[^]]+\]\((https?://[^)]+)\)$", re.IGNORECASE)
_ENTRY_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ENV_LOADED = False


def _load_environment() -> None:
    """Load repository and machine settings before any apps.* import."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars

    load_env_into_os()
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
    os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
    os.environ.update(machine_env_vars(load_machine_config(None)))
    _ENV_LOADED = True


def _now_singapore() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def _as_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return value.splitlines()
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise ValueError("Tags and references must be a string or list of strings.")


def _normalize_tag(value: str) -> str:
    value = value.strip().lstrip("#").casefold()
    return _TAG_TOKEN.sub("-", value).strip("-_")


def _normalize_tags(value: Any, *, is_reminder: bool) -> str:
    ordered = ["manual-entry", "notes"]
    if is_reminder:
        ordered.append("reminders")
    raw_items = _as_items(value)
    if len(raw_items) == 1:
        raw_items = re.split(r"[\s,]+", raw_items[0])
    for raw in raw_items:
        tag = _normalize_tag(raw)
        if tag and tag not in ordered:
            ordered.append(tag)
    rendered = " ".join(f"#{tag}" for tag in ordered)
    if len(rendered) > 2_000:
        raise ValueError("Tags exceed the HFL 2,000 character limit.")
    return rendered


def _normalize_references(value: Any) -> str:
    references: list[str] = []
    for raw in _as_items(value):
        candidate = re.sub(r"^\s*[-*]\s+", "", raw).strip()
        if not candidate:
            continue
        match = _MARKDOWN_LINK.fullmatch(candidate)
        target = match.group(1) if match else candidate
        parsed = urlsplit(target)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Reference must be an HTTP(S) URL: {candidate}")
        if candidate not in references:
            references.append(candidate)
    rendered = "\n".join(references)
    if len(rendered) > 20_000:
        raise ValueError("References exceed the HFL 20,000 character limit.")
    return rendered


def _required_text(payload: dict[str, Any], key: str, limit: int) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required.")
    if len(value) > limit:
        raise ValueError(f"{key} exceeds the HFL {limit:,} character limit.")
    return value


def prepare_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the API payload with skill invariants applied."""
    if not isinstance(raw, dict):
        raise ValueError("The note payload must be a JSON object.")
    now = _now_singapore()
    date_value = str(raw.get("date") or now.date().isoformat()).strip()
    time_value = str(raw.get("time") or now.strftime("%H:%M")).strip()
    try:
        date.fromisoformat(date_value)
        time.fromisoformat(time_value)
    except ValueError as exc:
        raise ValueError("date and time must use ISO formats YYYY-MM-DD and HH:MM.") from exc

    is_reminder_raw = raw.get("is_reminder", False)
    if not isinstance(is_reminder_raw, bool):
        raise ValueError("is_reminder must be true or false.")
    include_location = raw.get("include_location", False)
    if not isinstance(include_location, bool):
        raise ValueError("include_location must be true or false.")

    why_it_stayed = str(raw.get("why_it_stayed") or "").strip()
    possible_use = str(raw.get("possible_use") or "").strip()
    if len(why_it_stayed) > 10_000:
        raise ValueError("why_it_stayed exceeds the HFL 10,000 character limit.")
    if len(possible_use) > 5_000:
        raise ValueError("possible_use exceeds the HFL 5,000 character limit.")

    return {
        "date": date_value,
        "time": time_value,
        "moment": _required_text(raw, "moment", 500),
        "what_happened": _required_text(raw, "what_happened", 20_000),
        "why_it_stayed": why_it_stayed,
        "possible_use": possible_use,
        "source": "notes",
        "tags": _normalize_tags(raw.get("tags"), is_reminder=is_reminder_raw),
        "references": _normalize_references(raw.get("references")),
        "include_location": include_location,
    }


def validate_files(values: Iterable[str]) -> list[str]:
    paths = [Path(value).expanduser().resolve() for value in values]
    if len(paths) > MAX_FILES:
        raise ValueError(f"Select no more than {MAX_FILES} files.")
    total = 0
    normalized: list[str] = []
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Attachment is missing or unreadable: {path}")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f"Attachment exceeds 50 MB: {path.name}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Attachments exceed the 200 MB combined limit.")
        normalized.append(str(path))
    return normalized


def _clean_ocr_text(value: str) -> str:
    lines = [line.rstrip() for line in (value or "").replace("\r\n", "\n").split("\n")]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            cleaned.append(line.strip())
            blank = False
        elif cleaned and not blank:
            cleaned.append("")
            blank = True
    return "\n".join(cleaned).strip()


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    clipped = value[:limit].rstrip()
    boundary = max(clipped.rfind("\n"), clipped.rfind(" "))
    if boundary >= max(1, limit // 2):
        clipped = clipped[:boundary].rstrip()
    return clipped, True


def analyze_image(
    value: str,
    *,
    max_chars: int = DEFAULT_OCR_MAX_CHARS,
    ocr_func: Callable[[Any], str] | None = None,
) -> dict[str, Any]:
    """OCR one image locally; failures remain explicit and non-blocking."""
    path = Path(value).expanduser().resolve()
    result: dict[str, Any] = {"path": str(path), "filename": path.name}
    if path.suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
        return {**result, "status": "unsupported", "ocr_text": "", "truncated": False}
    try:
        from PIL import Image
        if ocr_func is None:
            import pytesseract
            ocr_func = pytesseract.image_to_string
        with Image.open(path) as source:
            source.seek(0)
            frame = source.convert("RGB")
            try:
                text = _clean_ocr_text(ocr_func(frame))
            finally:
                frame.close()
        bounded, truncated = _bounded_text(text, max_chars)
        return {
            **result,
            "status": "ok" if text else "no-text",
            "ocr_text": bounded,
            "characters": len(text),
            "truncated": truncated,
        }
    except Exception as exc:  # OCR is optional; never invent text on failure
        return {
            **result,
            "status": "error",
            "ocr_text": "",
            "truncated": False,
            "error_type": type(exc).__name__,
        }


def analyze_images(
    values: Iterable[str],
    *,
    max_chars: int = DEFAULT_OCR_MAX_CHARS,
    ocr_func: Callable[[Any], str] | None = None,
) -> dict[str, Any]:
    if not 1 <= max_chars <= 20_000:
        raise ValueError("OCR max characters must be between 1 and 20,000.")
    files = validate_files(values)
    return {
        "status": "analyzed",
        "images": [
            analyze_image(path, max_chars=max_chars, ocr_func=ocr_func)
            for path in files
        ],
    }


def _service():
    _load_environment()
    from apps.hfl_corpus.config import CONFIG
    from apps.hfl_corpus.references.web.api.entries import ApiServiceHflCorpusEntries

    return ApiServiceHflCorpusEntries(CONFIG)


def _document_service():
    _load_environment()
    from apps.hfl_corpus.config import CONFIG
    from apps.hfl_corpus.references.web.api.documents import (
        ApiServiceHflCorpusDocuments,
    )

    return ApiServiceHflCorpusDocuments(CONFIG)


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if is_dataclass(result):
        return asdict(result)
    return dict(vars(result)) if hasattr(result, "__dict__") else {}


def _deliver(
    payload: dict[str, Any],
    files: list[str],
    service_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    service = (service_factory or _service)()
    if files:
        return _as_dict(service.create_entry_with_uploads(file_paths=files, **payload))
    return _as_dict(service.create_entry(**payload))


def resolve_web_url(explicit: str | None = None) -> str:
    value = (explicit or os.environ.get("HFL_CORPUS_WEB_URL", "")).strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("HFL_CORPUS_WEB_URL must be an absolute HTTP(S) origin.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("HFL_CORPUS_WEB_URL must contain only the web origin.")
    return value


def document_url(web_url: str, payload: dict[str, Any], result: dict[str, Any]) -> str:
    filename = Path(str(result.get("path") or "")).name
    if not filename:
        filename = f"{payload['date']}.md"
    return f"{web_url}/hfl-corpus/document/{quote(filename, safe='')}"


def note_document_url(web_url: str, relative_path: str, anchor: str = "") -> str:
    """Return a browser link to one canonical corpus document or entry."""
    normalized = str(relative_path or "").replace("\\", "/").strip("/")
    if not normalized:
        raise ValueError("The note document path is missing.")
    url = f"{web_url}/hfl-corpus/document/{quote(normalized, safe='/')}"
    return f"{url}#{quote(anchor, safe='-')}" if anchor else url


def _parse_entry_item(item: dict[str, Any]):
    """Recover the canonical DTO embedded in a corpus entry search result."""
    _load_environment()
    from workflows.hfl.dto import HflEntry

    header = str(item.get("header") or "").strip()
    text = str(item.get("text") or "")
    first, separator, remainder = text.partition("\n")
    if first.strip().removeprefix("## ").strip() == header:
        body = remainder if separator else ""
    else:
        body = text
    return HflEntry.from_markdown(header, body)


def _timestamp_text(entry: Any, fallback: str = "") -> str:
    if entry.when is None:
        return fallback.strip()
    rendered = entry.when.strftime("%Y-%m-%d %H:%M")
    if entry.when.second or entry.when.microsecond:
        rendered = entry.when.isoformat(sep=" ", timespec="seconds")
    return rendered


def _one_line(value: str, limit: int = 240) -> str:
    rendered = " ".join(str(value or "").split())
    return rendered if len(rendered) <= limit else rendered[: limit - 3].rstrip() + "..."


def _note_summary(
    entry: Any,
    *,
    relative_path: str,
    anchor: str,
    web_url: str,
) -> dict[str, Any]:
    return {
        "guid": entry.entry_id,
        "what_happened": _one_line(entry.what_happened),
        "timestamp": _timestamp_text(entry),
        "document_hfl": note_document_url(web_url, relative_path, anchor),
    }


def recent_notes(
    *,
    limit: int,
    web_url: str,
    service_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Return table-ready recent canonical notes without exposing other sources."""
    if not 1 <= int(limit) <= 20:
        raise ValueError("Recent note limit must be between 1 and 20.")
    service = (service_factory or _document_service)()
    listing = _as_dict(service.list_documents(
        query="#manual-entry",
        sort="desc",
        page=1,
        page_size=20,
        compact=True,
        source="notes",
        include_secrets=True,
    ))
    notes: list[dict[str, Any]] = []
    for document in listing.get("results") or []:
        if len(notes) >= limit:
            break
        relative_path = str(document.get("relative_path") or "")
        if not relative_path:
            continue
        matches = _as_dict(service.list_matches(
            relative_path,
            query="#manual-entry",
            source="notes",
            offset=0,
            limit=min(20, limit - len(notes)),
            include_secrets=True,
        ))
        for item in matches.get("entries") or []:
            entry = _parse_entry_item(item)
            if (
                entry.source.casefold() != "notes"
                or "manual-entry" not in {tag.casefold() for tag in entry.tags}
                or not entry.entry_id
            ):
                continue
            notes.append(_note_summary(
                entry,
                relative_path=relative_path,
                anchor=str(item.get("anchor") or ""),
                web_url=web_url,
            ))
            if len(notes) >= limit:
                break
    notes.sort(key=lambda item: (item["timestamp"], item["guid"]), reverse=True)
    return {
        "status": "recent",
        "latest_document_url": notes[0]["document_hfl"] if notes else None,
        "notes": notes[:limit],
    }


def _find_note(
    guid: str,
    *,
    service: Any,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    normalized = str(guid or "").strip()
    if not re.fullmatch(r"hfl-[A-Za-z0-9-]{3,120}", normalized):
        raise ValueError("Note GUID must be a canonical hfl-* entry ID.")
    listing = _as_dict(service.list_documents(
        query=f"#manual-entry {normalized}",
        sort="desc",
        page=1,
        page_size=20,
        compact=True,
        source="notes",
        include_secrets=True,
    ))
    found: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []
    for document in listing.get("results") or []:
        relative_path = str(document.get("relative_path") or "")
        if not relative_path:
            continue
        response = _as_dict(service.get_document(
            relative_path,
            include_secrets=True,
        ))
        full_document = response.get("document") or {}
        for item in full_document.get("entries") or []:
            entry = _parse_entry_item(item)
            if (
                entry.entry_id == normalized
                and entry.source.casefold() == "notes"
                and "manual-entry" in {tag.casefold() for tag in entry.tags}
            ):
                found.append((entry, full_document, item))
    if not found:
        raise ValueError(
            f"No manual Source: notes entry found for GUID {normalized}."
        )
    if len(found) != 1:
        raise ValueError(f"GUID {normalized} is not unique in the canonical corpus.")
    return found[0]


def _full_note(
    entry: Any,
    *,
    document: dict[str, Any],
    item: dict[str, Any],
    web_url: str,
) -> dict[str, Any]:
    return {
        "guid": entry.entry_id,
        "timestamp": _timestamp_text(entry, str(item.get("header") or "")),
        "moment": entry.moment,
        "what_happened": entry.what_happened,
        "why_it_stayed": entry.why_it_stayed,
        "possible_use": entry.possible_use,
        "tags": list(entry.tags),
        "references": list(entry.references),
        "source": entry.source,
        "machine": entry.machine,
        "document_updated_at": str(document.get("updated_at") or ""),
        "document_hfl": note_document_url(
            web_url,
            str(document.get("relative_path") or ""),
            str(item.get("anchor") or ""),
        ),
    }


def get_note(
    guid: str,
    *,
    web_url: str,
    service_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    service = (service_factory or _document_service)()
    entry, document, item = _find_note(guid, service=service)
    return {
        "status": "found",
        "note": _full_note(
            entry,
            document=document,
            item=item,
            web_url=web_url,
        ),
    }


def _prepare_update(raw: dict[str, Any], current: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("The update payload must be a JSON object.")
    allowed = {
        "moment", "what_happened", "why_it_stayed", "possible_use",
        "tags", "references", "is_reminder",
    }
    unsupported = sorted(set(raw) - allowed)
    if unsupported:
        raise ValueError(
            "Unsupported update fields: " + ", ".join(unsupported)
            + ". Timestamp, source, machine, and GUID are immutable."
        )
    if not raw:
        raise ValueError("At least one note field must be updated.")

    changes: dict[str, Any] = {}
    for key, limit in (
        ("moment", 500),
        ("what_happened", 20_000),
        ("why_it_stayed", 10_000),
        ("possible_use", 5_000),
    ):
        if key not in raw:
            continue
        value = str(raw.get(key) or "").strip()
        if key in {"moment", "what_happened"} and not value:
            raise ValueError(f"{key} cannot be blank.")
        if len(value) > limit:
            raise ValueError(f"{key} exceeds the HFL {limit:,} character limit.")
        changes[key] = value

    if "references" in raw:
        rendered = _normalize_references(raw.get("references"))
        attachment_references = tuple(
            reference
            for reference in current.references
            if urlsplit(reference).scheme.casefold() not in {"http", "https"}
        )
        requested = tuple(rendered.splitlines()) if rendered else ()
        changes["references"] = tuple(
            dict.fromkeys((*attachment_references, *requested))
        )

    if "tags" in raw or "is_reminder" in raw:
        reminder = raw.get("is_reminder", "reminders" in current.tags)
        if not isinstance(reminder, bool):
            raise ValueError("is_reminder must be true or false.")
        raw_tags = raw.get("tags", list(current.tags))
        tag_items = [_normalize_tag(item) for item in _as_items(raw_tags)]
        if not reminder:
            tag_items = [item for item in tag_items if item != "reminders"]
        rendered = _normalize_tags(tag_items, is_reminder=reminder)
        changes["tags"] = tuple(token.lstrip("#") for token in rendered.split())

    effective = {
        key: value
        for key, value in changes.items()
        if getattr(current, key) != value
    }
    if not effective:
        raise ValueError("The update does not change the selected note.")
    return effective


def _replace_note_block(text: str, guid: str, updated: Any) -> str:
    _load_environment()
    from workflows.hfl.dto import HflEntry

    matches = list(_ENTRY_HEADER.finditer(text or ""))
    selected: list[tuple[int, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        parsed = HflEntry.from_markdown(match.group(1), text[match.end():end])
        if parsed.entry_id == guid:
            selected.append((match.start(), end))
    if len(selected) != 1:
        raise ValueError(
            f"Expected exactly one canonical block for {guid}; found {len(selected)}."
        )
    start, end = selected[0]
    return text[:start] + updated.to_markdown() + text[end:]


def _index_updated_note(entry: Any) -> str | None:
    _load_environment()
    from workflows.hfl.es_store import index_hfl_entry

    return index_hfl_entry(
        entry,
        source=entry.source,
        synthesized=bool(entry.synthesized),
        doc_id=entry.entry_id,
    )


def update_note(
    guid: str,
    raw: dict[str, Any],
    *,
    expected_updated_at: str,
    web_url: str,
    service_factory: Callable[[], Any] | None = None,
    index_func: Callable[[Any], str | None] | None = None,
) -> dict[str, Any]:
    """Replace one reviewed note block and upsert the same GUID in ES."""
    if not str(expected_updated_at or "").strip():
        raise ValueError("expected_updated_at is required for a safe note update.")
    service = (service_factory or _document_service)()
    current, document, item = _find_note(guid, service=service)
    observed = str(document.get("updated_at") or "")
    if observed != str(expected_updated_at).strip():
        raise ValueError(
            "The HFL document changed after review; retrieve the note again before updating."
        )
    changes = _prepare_update(raw, current)
    updated = replace(current, **changes)
    relative_path = str(document.get("relative_path") or "")
    replacement = _replace_note_block(
        str(document.get("text") or ""),
        current.entry_id,
        updated,
    )
    result = _as_dict(service.update_document(relative_path, replacement))
    if not result.get("updated"):
        raise RuntimeError("The canonical HFL document did not confirm the update.")
    try:
        doc_id = (index_func or _index_updated_note)(updated)
    except Exception:
        doc_id = None
    after = _full_note(
        updated,
        document=document,
        item=item,
        web_url=web_url,
    )
    return {
        "status": "updated",
        "before": _full_note(
            current,
            document=document,
            item=item,
            web_url=web_url,
        ),
        "after": after,
        "result": {
            **result,
            "entry_id": current.entry_id,
            "indexed": doc_id is not None,
            "doc_id": doc_id,
            "delivery": "persisted",
        },
        "document_url": after["document_hfl"],
    }


def resolve_outbox(explicit: str | None = None) -> Path:
    value = explicit or os.environ.get("WRITE_NOTES_OUTBOX_PATH", "")
    return Path(value).expanduser().resolve() if value else DEFAULT_OUTBOX.resolve()


def _outbox_key(payload: dict[str, Any], files: list[str]) -> str:
    encoded = json.dumps(
        {"payload": payload, "file_paths": files},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def save_outbox(
    payload: dict[str, Any], files: list[str], web_url: str, root: Path
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"note-{_outbox_key(payload, files)}.json"
    temporary = target.with_suffix(".json.tmp")
    record = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "file_paths": files,
        "web_url": web_url,
    }
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def submit_or_outbox(
    raw: dict[str, Any],
    file_values: Iterable[str],
    *,
    web_url: str,
    outbox_root: Path,
    service_factory: Callable[[], Any] | None = None,
) -> tuple[dict[str, Any], int]:
    payload = prepare_payload(raw)
    files = validate_files(file_values)
    try:
        result = _deliver(payload, files, service_factory)
    except Exception as exc:  # retain retry state without serializing credentials/errors
        path = save_outbox(payload, files, web_url, outbox_root)
        return ({
            "status": "outbox",
            "preview": payload,
            "outbox": str(path),
            "error_type": type(exc).__name__,
            "message": "Submission failed; retry payload saved.",
        }, 1)
    return ({
        "status": "submitted",
        "preview": payload,
        "result": result,
        "document_url": document_url(web_url, payload, result),
    }, 0)


def retry_items(
    root: Path,
    selected: Iterable[str],
    *,
    service_factory: Callable[[], Any] | None = None,
) -> tuple[dict[str, Any], int]:
    paths = [Path(value).expanduser().resolve() for value in selected]
    if not paths:
        paths = sorted(root.glob("note-*.json")) if root.is_dir() else []
    outcomes: list[dict[str, Any]] = []
    failed = False
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("schema_version") != 1:
                raise ValueError("Unsupported outbox schema version.")
            payload = prepare_payload(record["payload"])
            files = validate_files(record.get("file_paths", []))
            web_url = resolve_web_url(record.get("web_url"))
            result = _deliver(payload, files, service_factory)
            path.unlink()
            outcomes.append({
                "outbox": str(path),
                "status": "submitted",
                "result": result,
                "document_url": document_url(web_url, payload, result),
            })
        except Exception as exc:
            failed = True
            outcomes.append({
                "outbox": str(path),
                "status": "retained",
                "error_type": type(exc).__name__,
            })
    return ({"status": "partial" if failed else "complete", "items": outcomes}, int(failed))


def _read_json(value: str) -> dict[str, Any]:
    text = sys.stdin.read() if value == "-" else Path(value).read_text(encoding="utf-8")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("The note payload must be a JSON object.")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview", help="Validate and print a payload without writing")
    preview.add_argument("--json", required=True, help="JSON file path, or - for stdin")
    analyze = commands.add_parser("analyze-images", help="Run local OCR without writing")
    analyze.add_argument("--file", action="append", required=True, help="Image attachment path")
    analyze.add_argument("--max-chars", type=int, default=DEFAULT_OCR_MAX_CHARS)
    submit = commands.add_parser("submit", help="Submit a note or retain it in the outbox")
    submit.add_argument("--json", required=True, help="JSON file path, or - for stdin")
    submit.add_argument("--file", action="append", default=[], help="Explicit attachment path")
    submit.add_argument("--web-url")
    submit.add_argument("--outbox-dir")
    retry = commands.add_parser("retry", help="Retry retained submissions")
    retry.add_argument("--item", action="append", default=[], help="Specific outbox JSON path")
    retry.add_argument("--outbox-dir")
    recent = commands.add_parser("recent", help="List recent canonical Source: notes entries")
    recent.add_argument("--limit", type=int, default=10)
    recent.add_argument("--web-url")
    get = commands.add_parser("get", help="Retrieve one canonical note by GUID")
    get.add_argument("--guid", required=True)
    get.add_argument("--web-url")
    update = commands.add_parser("update", help="Update one reviewed note by GUID")
    update.add_argument("--guid", required=True)
    update.add_argument("--json", required=True, help="JSON file path, or - for stdin")
    update.add_argument("--expected-updated-at", required=True)
    update.add_argument("--web-url")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preview":
            output, code = {"status": "preview", "preview": prepare_payload(_read_json(args.json))}, 0
        elif args.command == "analyze-images":
            output, code = analyze_images(args.file, max_chars=args.max_chars), 0
        elif args.command in {"recent", "get", "update"}:
            _load_environment()
            web_url = resolve_web_url(args.web_url)
            if args.command == "recent":
                output, code = recent_notes(limit=args.limit, web_url=web_url), 0
            elif args.command == "get":
                output, code = get_note(args.guid, web_url=web_url), 0
            else:
                output, code = update_note(
                    args.guid,
                    _read_json(args.json),
                    expected_updated_at=args.expected_updated_at,
                    web_url=web_url,
                ), 0
        else:
            _load_environment()
            root = resolve_outbox(args.outbox_dir)
            if args.command == "submit":
                output, code = submit_or_outbox(
                    _read_json(args.json),
                    args.file,
                    web_url=resolve_web_url(args.web_url),
                    outbox_root=root,
                )
            else:
                output, code = retry_items(root, args.item)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        output, code = {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }, 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
