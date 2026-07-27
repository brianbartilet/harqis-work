#!/usr/bin/env python3
"""Remove insecure HTTP references from the HFL Markdown and ES stores.

Usage:
    python scripts/agents/hfl/migrate_references.py
    python scripts/agents/hfl/migrate_references.py --apply
    python scripts/agents/hfl/migrate_references.py --corpus /path/to/corpus

The command is a dry-run unless ``--apply`` is supplied. Apply mode backs up
every affected Markdown file and Elasticsearch document before changing either
store. Reports contain counts and entry IDs, never reference values.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INDEX = "harqis-hfl-entries"
DEFAULT_BACKUP_ROOT = REPO_ROOT / ".harqis-data" / "hfl-reference-migrations"
_ENTRY_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ENTRY_ID = re.compile(r"^\s*Entry ID:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_REFERENCES = re.compile(r"^\s*References:\s*$", re.IGNORECASE)
_REFERENCE_BULLET = re.compile(r"^\s*[-*•]\s+(.+?)\s*$")


def is_insecure_http(reference: str) -> bool:
    return (reference or "").strip().casefold().startswith("http://")


def safe_report_id(value: str, fallback: str = "unknown-entry") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", (value or "").strip()).strip("-")
    return cleaned[:160] or fallback


@dataclass(frozen=True)
class MarkdownChange:
    path: Path
    updated_text: str
    entry_ids: tuple[str, ...]
    removed: int


@dataclass(frozen=True)
class ElasticsearchChange:
    index: str
    doc_id: str
    source: dict[str, Any]
    updated_references: tuple[str, ...]
    entry_id: str
    removed: int


@dataclass(frozen=True)
class MigrationSummary:
    markdown_files: int
    elasticsearch_documents: int
    references_removed: int
    entry_ids: tuple[str, ...]
    applied: bool
    backup_dir: Path | None = None


def _migrate_entry_block(
    block: str,
    *,
    fallback_id: str,
) -> tuple[str, str, int]:
    match = _ENTRY_ID.search(block)
    entry_id = safe_report_id(match.group(1) if match else fallback_id, fallback_id)
    lines = block.splitlines(keepends=True)
    remove_indexes: set[int] = set()
    removed = 0
    index = 0
    while index < len(lines):
        if not _REFERENCES.match(lines[index].strip()):
            index += 1
            continue
        header_index = index
        bullet_indexes: list[int] = []
        kept_bullets = 0
        index += 1
        while index < len(lines):
            stripped = lines[index].strip()
            bullet = _REFERENCE_BULLET.match(stripped)
            if bullet:
                bullet_indexes.append(index)
                if is_insecure_http(bullet.group(1)):
                    remove_indexes.add(index)
                    removed += 1
                else:
                    kept_bullets += 1
                index += 1
                continue
            if not stripped:
                index += 1
                continue
            break
        if bullet_indexes and kept_bullets == 0:
            remove_indexes.add(header_index)
    if not removed:
        return block, entry_id, 0
    return (
        "".join(line for line_index, line in enumerate(lines) if line_index not in remove_indexes),
        entry_id,
        removed,
    )


def migrate_markdown_text(text: str) -> tuple[str, tuple[str, ...], int]:
    matches = list(_ENTRY_HEADER.finditer(text or ""))
    if not matches:
        return text, (), 0
    output = [text[: matches[0].start()]]
    affected_ids: list[str] = []
    removed = 0
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block, entry_id, block_removed = _migrate_entry_block(
            text[match.start():end],
            fallback_id=f"legacy-entry-{index + 1}",
        )
        output.append(block)
        if block_removed:
            affected_ids.append(entry_id)
            removed += block_removed
    return "".join(output), tuple(affected_ids), removed


def scan_markdown(corpus_root: Path) -> list[MarkdownChange]:
    root = Path(corpus_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("The HFL corpus directory does not exist.")
    changes: list[MarkdownChange] = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        original = path.read_text(encoding="utf-8")
        updated, entry_ids, removed = migrate_markdown_text(original)
        if removed:
            changes.append(MarkdownChange(path, updated, entry_ids, removed))
    return changes


class ElasticsearchClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: int = 20,
    ) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ELASTIC_HOST must be an absolute HTTP(S) URL.")
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        data = raw_body
        if data is None and body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": content_type, **self.headers},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            exc.read()
            raise RuntimeError(f"Elasticsearch returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Elasticsearch is unavailable.") from exc
        return json.loads(payload or b"{}")

    def scan(self, index: str) -> list[ElasticsearchChange]:
        encoded_index = urllib.parse.quote(index, safe="-_.")
        response = self._request(
            "POST",
            f"/{encoded_index}/_search?scroll=1m",
            {
                "size": 500,
                "sort": ["_doc"],
                "query": {"match_all": {}},
            },
        )
        scroll_id = str(response.get("_scroll_id") or "")
        changes: list[ElasticsearchChange] = []
        try:
            while True:
                hits = response.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for hit in hits:
                    source = hit.get("_source")
                    if not isinstance(source, dict):
                        continue
                    references = source.get("references")
                    if not isinstance(references, list):
                        continue
                    updated = tuple(
                        str(reference)
                        for reference in references
                        if not is_insecure_http(str(reference))
                    )
                    removed = len(references) - len(updated)
                    if not removed:
                        continue
                    doc_id = str(hit.get("_id") or "")
                    entry_id = safe_report_id(
                        str(source.get("entry_id") or doc_id or "unknown-entry")
                    )
                    changes.append(
                        ElasticsearchChange(
                            index=str(hit.get("_index") or index),
                            doc_id=doc_id,
                            source=copy.deepcopy(source),
                            updated_references=updated,
                            entry_id=entry_id,
                            removed=removed,
                        )
                    )
                if not scroll_id:
                    break
                response = self._request(
                    "POST",
                    "/_search/scroll",
                    {"scroll": "1m", "scroll_id": scroll_id},
                )
                scroll_id = str(response.get("_scroll_id") or scroll_id)
        finally:
            if scroll_id:
                try:
                    self._request("DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})
                except RuntimeError:
                    pass
        return changes

    def update_references(
        self,
        changes: Iterable[ElasticsearchChange],
        *,
        restore: bool = False,
    ) -> None:
        lines: list[str] = []
        for change in changes:
            references = (
                tuple(str(item) for item in change.source.get("references", []))
                if restore
                else change.updated_references
            )
            lines.append(
                json.dumps(
                    {"update": {"_index": change.index, "_id": change.doc_id}},
                    separators=(",", ":"),
                )
            )
            lines.append(
                json.dumps(
                    {"doc": {"references": list(references)}},
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
        if not lines:
            return
        response = self._request(
            "POST",
            "/_bulk",
            raw_body=("\n".join(lines) + "\n").encode("utf-8"),
            content_type="application/x-ndjson",
        )
        if response.get("errors"):
            raise RuntimeError("Elasticsearch rejected one or more reference updates.")


def _load_env_file() -> None:
    try:
        from scripts.deploy import (
            load_env_into_os,
            load_machine_config,
            machine_env_vars,
        )

        load_env_into_os()
        os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
        os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
        os.environ.update(machine_env_vars(load_machine_config(None)))
        return
    except Exception:
        pass
    env_file = REPO_ROOT / ".env" / "apps.env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def elasticsearch_client_from_env() -> ElasticsearchClient:
    base_url = (os.environ.get("ES_HOST") or os.environ.get("ELASTIC_HOST") or "").strip()
    if not base_url or "${" in base_url:
        raise ValueError("ELASTIC_HOST is not configured.")
    headers: dict[str, str] = {}
    api_key = os.environ.get("ELASTIC_API_KEY", "").strip()
    user = os.environ.get("ELASTIC_USER", "").strip()
    password = os.environ.get("ELASTIC_PASSWORD", "")
    if api_key and "${" not in api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    elif user and password and "${" not in user and "${" not in password:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    return ElasticsearchClient(base_url, headers=headers)


def resolve_corpus_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("HFL_CORPUS_PATH", "").strip()
    if configured and "${" not in configured:
        return Path(configured).expanduser().resolve()
    try:
        from apps.apps_config import CONFIG_MANAGER

        hfl = CONFIG_MANAGER.get("HFL")
        configured = (hfl.get("corpus") or {}).get("path") if isinstance(hfl, dict) else None
        if configured and "${" not in configured:
            return Path(configured).expanduser().resolve()
    except Exception as exc:
        raise ValueError("The HFL corpus path could not be resolved.") from exc
    raise ValueError("The HFL corpus path is not configured.")


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _create_backup(
    corpus_root: Path,
    markdown_changes: list[MarkdownChange],
    es_changes: list[ElasticsearchChange],
    backup_root: Path,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(backup_root).expanduser().resolve() / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(backup_dir, 0o700)
    markdown_dir = backup_dir / "markdown"
    for change in markdown_changes:
        relative = change.path.resolve().relative_to(corpus_root.resolve())
        destination = markdown_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(change.path, destination)
        os.chmod(destination, 0o600)
    es_backup = backup_dir / "elasticsearch.json"
    es_backup.write_text(
        json.dumps(
            [
                {
                    "_index": change.index,
                    "_id": change.doc_id,
                    "_source": change.source,
                }
                for change in es_changes
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.chmod(es_backup, 0o600)
    return backup_dir


def _restore_markdown(
    corpus_root: Path,
    markdown_changes: list[MarkdownChange],
    backup_dir: Path,
) -> None:
    for change in markdown_changes:
        relative = change.path.resolve().relative_to(corpus_root.resolve())
        backup = backup_dir / "markdown" / relative
        if backup.is_file():
            shutil.copy2(backup, change.path)


def run_migration(
    corpus_root: Path,
    es_client: ElasticsearchClient,
    *,
    index: str = DEFAULT_INDEX,
    apply: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
) -> MigrationSummary:
    root = Path(corpus_root).expanduser().resolve()
    markdown_changes = scan_markdown(root)
    es_changes = es_client.scan(index)
    entry_ids = tuple(
        dict.fromkeys(
            entry_id
            for change in markdown_changes
            for entry_id in change.entry_ids
        )
        | dict.fromkeys(change.entry_id for change in es_changes)
    )
    removed = sum(change.removed for change in markdown_changes) + sum(
        change.removed for change in es_changes
    )
    if not apply or not removed:
        return MigrationSummary(
            markdown_files=len(markdown_changes),
            elasticsearch_documents=len(es_changes),
            references_removed=removed,
            entry_ids=entry_ids,
            applied=False,
        )

    backup_dir = _create_backup(root, markdown_changes, es_changes, backup_root)
    try:
        es_client.update_references(es_changes)
        for change in markdown_changes:
            _atomic_write(change.path, change.updated_text)
    except Exception:
        _restore_markdown(root, markdown_changes, backup_dir)
        try:
            es_client.update_references(es_changes, restore=True)
        except Exception:
            pass
        raise
    return MigrationSummary(
        markdown_files=len(markdown_changes),
        elasticsearch_documents=len(es_changes),
        references_removed=removed,
        entry_ids=entry_ids,
        applied=True,
        backup_dir=backup_dir,
    )


def _print_summary(summary: MigrationSummary) -> None:
    mode = "applied" if summary.applied else "dry-run"
    print(f"HFL reference migration ({mode})")
    print(f"  Markdown files: {summary.markdown_files}")
    print(f"  Elasticsearch documents: {summary.elasticsearch_documents}")
    print(f"  Reference copies removed: {summary.references_removed}")
    print("  Entry IDs:")
    for entry_id in summary.entry_ids:
        print(f"    - {entry_id}")
    if not summary.entry_ids:
        print("    (none)")
    if summary.backup_dir:
        print(f"  Backup: {summary.backup_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up and update Markdown plus Elasticsearch (default: dry-run).",
    )
    parser.add_argument("--corpus", help="Override the configured HFL corpus directory.")
    parser.add_argument(
        "--index",
        default=os.environ.get("HFL_ES_INDEX", "").strip() or DEFAULT_INDEX,
        help=f"Elasticsearch index (default: {DEFAULT_INDEX}).",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=DEFAULT_BACKUP_ROOT,
        help="Directory for apply-mode backups.",
    )
    args = parser.parse_args()
    _load_env_file()
    try:
        summary = run_migration(
            resolve_corpus_root(args.corpus),
            elasticsearch_client_from_env(),
            index=args.index,
            apply=args.apply,
            backup_root=args.backup_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
