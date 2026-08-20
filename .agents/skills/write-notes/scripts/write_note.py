"""Validate and submit structured notes to the HFL Corpus API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTBOX = REPO_ROOT / "logs" / "write-notes-outbox"
MAX_FILES = 10
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
_TAG_TOKEN = re.compile(r"[^\w-]+", re.UNICODE)
_MARKDOWN_LINK = re.compile(r"^\[[^]]+\]\((https?://[^)]+)\)$", re.IGNORECASE)
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


def _service():
    _load_environment()
    from apps.hfl_corpus.config import CONFIG
    from apps.hfl_corpus.references.web.api.entries import ApiServiceHflCorpusEntries

    return ApiServiceHflCorpusEntries(CONFIG)


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
    submit = commands.add_parser("submit", help="Submit a note or retain it in the outbox")
    submit.add_argument("--json", required=True, help="JSON file path, or - for stdin")
    submit.add_argument("--file", action="append", default=[], help="Explicit attachment path")
    submit.add_argument("--web-url")
    submit.add_argument("--outbox-dir")
    retry = commands.add_parser("retry", help="Retry retained submissions")
    retry.add_argument("--item", action="append", default=[], help="Specific outbox JSON path")
    retry.add_argument("--outbox-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preview":
            output, code = {"status": "preview", "preview": prepare_payload(_read_json(args.json))}, 0
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
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        output, code = {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }, 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
