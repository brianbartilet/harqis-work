#!/usr/bin/env python3
"""Reclassify legacy HFL ``media`` sources by canonical dump provenance.

Dry-run is the default. ``--apply`` backs up affected Markdown bytes and full
Elasticsearch documents, preserves entry IDs, reclassifies source in both
stores, and restores precise timestamps/synthesis metadata in shared Markdown
entries from their existing Elasticsearch projection. Unresolvable records
remain ``media`` and are reported by ID only.
"""

from __future__ import annotations

import argparse
import base64
import copy
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Never

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Importing the shared classifier initializes the HFL task package. Keep the
# standalone migration CLI usable before application environment loading.
for _key, _default in {
    "PATH_APP_CONFIG": str(REPO_ROOT),
    "APP_CONFIG_FILE": "apps_config.yaml",
    "WORKFLOW_CONFIG": "workflows.config",
}.items():
    os.environ[_key] = os.environ.get(_key, _default).strip()

from scripts.agents.hfl.migrate_references import (  # noqa: E402
    DEFAULT_INDEX,
    ElasticsearchClient as _BaseElasticsearchClient,
    _load_env_file,
    elasticsearch_client_from_env as _base_client_from_env,
    resolve_corpus_root,
    safe_report_id,
)
from workflows.hfl.tasks.analyze_media import classify_media_source  # noqa: E402
from workflows.hfl.write_lock import corpus_write_lock  # noqa: E402

DEFAULT_BACKUP_ROOT = REPO_ROOT / ".harqis-data" / "hfl-media-source-migrations"
_ENTRY_HEADER = re.compile(
    r"^##\s+(?P<title>\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?)\s*$"
)
_FENCE = re.compile(r"^\s*(?P<marker>`{3,}|~{3,})")
_ENTRY_ID = re.compile(
    r"^[ \t]*Entry ID:[ \t]*(.+?)[ \t]*(?=\r?$)",
    re.MULTILINE | re.IGNORECASE,
)
_ENTRY_ID_FIELD = re.compile(
    r"(?m)^Entry ID:[ \t]+(?P<value>[^\r\n]+?)[ \t]*\r?$"
)
_NARRATIVE_FIELD = re.compile(
    r"(?m)^(?:Moment|What happened|Why it stayed|Possible use|Tags|References):"
)
_SOURCE_FIELD = re.compile(
    r"(?m)^(?P<prefix>Source:[ \t]+)(?P<value>[^\r\n]+?)(?P<suffix>[ \t]*\r?)$"
)
_SYNTHESIZED = re.compile(
    r"^[ \t]*Synthesized:[ \t]*(?:true|false)[ \t]*(?=\r?$)",
    re.MULTILINE | re.IGNORECASE,
)
_REFERENCE = re.compile(r"^\s*[-*•]\s+(.+?)\s*$")
_SOURCE_TOKEN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
APPROVED_SOURCE_RENAMES = {
    "echomtg_inventory": "echomtg-inventory",
    "android_capture": "android-capture",
}


def _validated_source_renames(
    source_renames: Mapping[str, str] | None,
) -> dict[str, str] | None:
    if source_renames is None:
        return None
    validated = dict(source_renames)
    if not validated:
        raise ValueError("At least one approved source rename is required.")
    for old, new in validated.items():
        if not isinstance(old, str) or not isinstance(new, str):
            raise ValueError("Source rename labels must be strings.")
        if old != old.strip() or new != new.strip() or old == new:
            raise ValueError(f"Invalid HFL source rename: {old!r} -> {new!r}.")
        if not _SOURCE_TOKEN.fullmatch(new):
            raise ValueError(f"Invalid canonical HFL source label: {new!r}.")
        if APPROVED_SOURCE_RENAMES.get(old) != new:
            raise ValueError(f"Unapproved HFL source rename: {old!r} -> {new!r}.")
    if set(validated).intersection(validated.values()):
        raise ValueError("Source rename chains/cycles are not supported.")
    return validated



@dataclass(frozen=True)
class SourceChange:
    entry_id: str
    old_source: str
    new_source: str


@dataclass(frozen=True)
class MarkdownFileChange:
    path: Path
    original_text: str
    updated_text: str
    changes: tuple[SourceChange, ...]
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class EntryHeader:
    start: int
    end: int
    title: str


@dataclass(frozen=True)
class MarkdownScan:
    changes: tuple[MarkdownFileChange, ...]
    unresolved_ids: tuple[str, ...]
    source_counts: dict[str, int]
    entry_sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ElasticsearchChange:
    index: str
    doc_id: str
    entry_id: str
    old_source: str
    new_source: str
    document: dict[str, Any]
    seq_no: int | None = None
    primary_term: int | None = None


class BulkUpdateError(RuntimeError):
    def __init__(
        self,
        message: str,
        applied_changes: tuple[ElasticsearchChange, ...] = (),
    ) -> None:
        super().__init__(message)
        self.applied_changes = applied_changes


@dataclass(frozen=True)
class ElasticsearchScan:
    changes: tuple[ElasticsearchChange, ...]
    unresolved_ids: tuple[str, ...]
    entry_sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MigrationSummary:
    markdown_entries: int
    markdown_files: int
    elasticsearch_documents: int
    unresolved_markdown: int
    unresolved_elasticsearch: int
    source_counts: dict[str, int]
    applied: bool
    backup_dir: Path | None = None


def _entry_headers(text: str) -> tuple[EntryHeader, ...]:
    headers: list[EntryHeader] = []
    offset = 0
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        marker_match = _FENCE.match(body)
        if marker_match:
            marker = marker_match.group("marker")
            marker_key = marker[0]
            if fence is None:
                fence = (marker_key, len(marker))
            elif marker_key == fence[0] and len(marker) >= fence[1]:
                fence = None
            offset += len(line)
            continue
        if fence is None and (match := _ENTRY_HEADER.match(body)):
            headers.append(EntryHeader(offset, offset + len(body), match.group("title")))
        offset += len(line)
    return tuple(headers)


def _file_identity(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        stat.S_IMODE(file_stat.st_mode),
    )


def _reject_symlink_components(path: Path) -> None:
    current = path.expanduser().absolute()
    while current != current.parent:
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise RuntimeError(f"Refusing symlinked corpus path: {current}.")
        except FileNotFoundError:
            pass
        current = current.parent


def _read_markdown_exact(
    path: Path,
    expected_identity: tuple[int, int, int, int, int] | None = None,
    *,
    dir_fd: int | None = None,
) -> tuple[str, tuple[int, int, int, int, int]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path.name if dir_fd is not None else path, flags, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK} or path.is_symlink():
            raise RuntimeError(f"Refusing symlinked HFL corpus file: {path.name}") from exc
        raise
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(f"Refusing non-regular HFL corpus file: {path.name}")
        identity = _file_identity(file_stat)
        if expected_identity is not None and identity != expected_identity:
            raise RuntimeError(f"Concurrent HFL corpus change detected for {path.name}.")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read()
    finally:
        os.close(descriptor)
    try:
        return payload.decode("utf-8"), identity
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"HFL corpus file is not UTF-8 Markdown: {path.name}") from exc


def _references_from_block(block: str) -> tuple[str, ...]:
    """Return only the canonical, visible References field for one entry."""
    lines = block.splitlines()
    references: list[str] = []
    in_references = False
    reference_fields = 0
    fence: tuple[str, int] | None = None
    previous_visible = ""
    for line in lines:
        marker_match = _FENCE.match(line)
        if marker_match:
            marker = marker_match.group("marker")
            marker_key = marker[0]
            if fence is None:
                fence = (marker_key, len(marker))
            elif marker_key == fence[0] and len(marker) >= fence[1]:
                fence = None
            continue
        if fence is not None:
            continue
        if line == "References:":
            reference_fields += 1
            if reference_fields > 1:
                raise RuntimeError(
                    "HFL entry must contain at most one canonical References field."
                )
            if not re.match(r"^Tags:[ \t]", previous_visible):
                raise RuntimeError(
                    "HFL entry References field is not in canonical position."
                )
            in_references = True
            previous_visible = line
            continue
        if not in_references:
            if line.strip():
                previous_visible = line
            continue
        bullet = _REFERENCE.match(line)
        if bullet:
            references.append(bullet.group(1).strip())
            previous_visible = line
            continue
        if line.strip():
            in_references = False
            previous_visible = line
    return tuple(references)


def _relative_dump_path(reference: str) -> Path | None:
    raw = (reference or "").strip()
    if not raw.startswith("/"):
        return None
    root = Path("/Volumes/harqis-data/dumps")
    if os.path.normpath(raw) != raw:
        return None
    path = Path(raw)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    from workflows.dumps.files import parse_dump_dir_name

    if parts and parse_dump_dir_name(parts[0].casefold()):
        return relative
    return None


def classify_references(references: Iterable[str]) -> str | None:
    sources = {
        source
        for reference in references
        if (relative := _relative_dump_path(reference)) is not None
        if (source := classify_media_source(relative)) is not None
    }
    return next(iter(sources)) if len(sources) == 1 else None


def _canonical_entry_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw or safe_report_id(raw, "") != raw:
        raise RuntimeError("HFL entry has an invalid canonical Entry ID.")
    return raw


def _migrate_entry_block(
    block: str,
    source_renames: Mapping[str, str] | None = None,
) -> tuple[str, SourceChange | None, str | None]:
    source_fields = tuple(_SOURCE_FIELD.finditer(block))
    if not source_fields:
        return block, None, None
    if len(source_fields) != 1:
        raise RuntimeError("HFL entry must contain exactly one canonical Source field.")
    source_match = source_fields[0]
    header_end = block.find("\n") + 1
    if header_end <= 0 or source_match.start() != header_end:
        raise RuntimeError("HFL entry Source field is not in canonical position.")
    old_source = source_match.group("value").strip()
    if source_renames is None:
        if old_source.casefold() != "media":
            return block, None, None
    elif old_source not in source_renames:
        return block, None, None
    id_fields = tuple(_ENTRY_ID_FIELD.finditer(block))
    narrative_match = _NARRATIVE_FIELD.search(block)
    if (
        len(id_fields) != 1
        or id_fields[0].start() <= source_match.end()
        or (narrative_match is not None and id_fields[0].start() >= narrative_match.start())
    ):
        raise RuntimeError(
            "Classifiable HFL source entry lacks one canonical metadata Entry ID."
        )
    entry_id = _canonical_entry_id(id_fields[0].group("value"))
    new_source = (
        classify_references(_references_from_block(block))
        if source_renames is None
        else source_renames[old_source]
    )
    if new_source is None:
        return block, None, entry_id
    updated = block[:source_match.start()] + source_match.group("prefix") + new_source + source_match.group("suffix") + block[source_match.end():]
    return updated, SourceChange(entry_id, old_source, new_source), None


def migrate_markdown_text(
    text: str,
    source_renames: Mapping[str, str] | None = None,
) -> tuple[str, tuple[SourceChange, ...], tuple[str, ...]]:
    headers = _entry_headers(text or "")
    if not headers:
        return text, (), ()
    output = [text[:headers[0].start]]
    changes: list[SourceChange] = []
    unresolved: list[str] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start if index + 1 < len(headers) else len(text)
        updated, change, unresolved_id = _migrate_entry_block(
            text[header.start:end], source_renames,
        )
        output.append(updated)
        if change:
            changes.append(change)
        if unresolved_id:
            unresolved.append(unresolved_id)
    return "".join(output), tuple(changes), tuple(unresolved)


def _open_directory_no_follow(path: Path) -> tuple[Path, int]:
    absolute = Path(os.path.abspath(Path(path).expanduser()))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
    except Exception:
        os.close(descriptor)
        raise
    return absolute, descriptor


def _open_relative_directory_no_follow(root_fd: int, relative: Path) -> int:
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise RuntimeError(f"Invalid corpus-relative directory: {relative}.")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.dup(root_fd)
    try:
        for part in relative.parts:
            child = os.open(part, flags, dir_fd=descriptor)
            if not stat.S_ISDIR(os.fstat(child).st_mode):
                os.close(child)
                raise RuntimeError(f"Refusing non-directory corpus path: {relative}.")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _change_parent_directory(corpus_root: Path, corpus_fd: int, path: Path):
    relative = path.relative_to(corpus_root)
    if not relative.parts or relative.name.startswith("."):
        raise RuntimeError(f"Invalid HFL corpus path: {relative}.")
    parent_relative = relative.parent
    parent_fd = _open_relative_directory_no_follow(corpus_fd, parent_relative)
    try:
        _verify_directory_binding(corpus_root / parent_relative, parent_fd)
        yield relative, parent_fd
    finally:
        os.close(parent_fd)


def _markdown_files_from_fd(
    root: Path,
    descriptor: int,
    relative: Path = Path(),
):
    for name in sorted(os.listdir(descriptor)):
        if name.startswith("."):
            continue
        item = relative / name
        item_stat = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISLNK(item_stat.st_mode):
            raise RuntimeError(f"Refusing symlinked HFL corpus path: {item}")
        if stat.S_ISDIR(item_stat.st_mode):
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            child_fd = os.open(name, flags, dir_fd=descriptor)
            try:
                yield from _markdown_files_from_fd(root, child_fd, item)
            finally:
                os.close(child_fd)
            continue
        if not name.endswith(".md"):
            continue
        if not stat.S_ISREG(item_stat.st_mode):
            raise RuntimeError(f"Refusing non-regular HFL corpus file: {item}")
        try:
            text, identity = _read_markdown_exact(
                Path(name), _file_identity(item_stat), dir_fd=descriptor,
            )
        finally:
            os.utime(
                name,
                ns=(item_stat.st_atime_ns, item_stat.st_mtime_ns),
                dir_fd=descriptor,
                follow_symlinks=False,
            )
        yield item, text, identity


def scan_markdown(
    corpus_root: Path,
    *,
    corpus_fd: int | None = None,
    source_renames: Mapping[str, str] | None = None,
) -> MarkdownScan:
    raw_root = Path(corpus_root)
    _reject_symlink_components(raw_root)
    owned_fd = corpus_fd is None
    if corpus_fd is None:
        root, corpus_fd = _open_directory_no_follow(raw_root)
    else:
        root = Path(os.path.abspath(raw_root.expanduser()))
    if corpus_fd is None:
        raise RuntimeError("A retained corpus directory descriptor is required.")
    file_changes: list[MarkdownFileChange] = []
    unresolved: list[str] = []
    counts: Counter[str] = Counter()
    seen_ids: dict[str, Path] = {}
    entry_sources: dict[str, str] = {}
    try:
        for relative, original, identity in _markdown_files_from_fd(root, corpus_fd):
            path = root / relative
            headers = _entry_headers(original)
            for index, header in enumerate(headers):
                end = headers[index + 1].start if index + 1 < len(headers) else len(original)
                block = original[header.start:end]
                id_match = _ENTRY_ID.search(block)
                if not id_match:
                    continue
                entry_id = id_match.group(1).strip()
                if previous := seen_ids.get(entry_id):
                    raise RuntimeError(
                        f"Duplicate HFL entry ID {entry_id} in "
                        f"{previous.name} and {path.name}."
                    )
                seen_ids[entry_id] = path
                source_fields = tuple(_SOURCE_FIELD.finditer(block))
                if len(source_fields) == 1:
                    entry_sources[entry_id] = source_fields[0].group("value").strip()
            updated, changes, unresolved_ids = migrate_markdown_text(
                original, source_renames,
            )
            unresolved.extend(unresolved_ids)
            counts.update(change.new_source for change in changes)
            if changes:
                file_changes.append(
                    MarkdownFileChange(path, original, updated, changes, identity)
                )
        return MarkdownScan(
            tuple(file_changes),
            tuple(unresolved),
            dict(sorted(counts.items())),
            entry_sources,
        )
    finally:
        if owned_fd:
            os.close(corpus_fd)


def _format_markdown_time(value: str) -> str | None:
    try:
        when = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    rendered = when.strftime("%Y-%m-%d %H:%M")
    if when.second or when.microsecond:
        rendered = when.strftime("%Y-%m-%d %H:%M:%S")
        if when.microsecond:
            fraction = f"{when.microsecond:06d}".rstrip("0").ljust(3, "0")
            rendered += f".{fraction}"
    return rendered


def enrich_markdown_metadata(text: str, documents: dict[str, dict[str, Any]]) -> str:
    """Restore exact ES time/synthesis metadata without re-rendering entry prose."""
    headers = _entry_headers(text or "")
    if not headers or not documents:
        return text
    output = [text[:headers[0].start]]
    for index, header in enumerate(headers):
        end = headers[index + 1].start if index + 1 < len(headers) else len(text)
        block = text[header.start:end]
        id_match = _ENTRY_ID.search(block)
        document = documents.get(id_match.group(1).strip()) if id_match else None
        if not document:
            output.append(block)
            continue
        precise = _format_markdown_time(str(document.get("when") or ""))
        canonical_minute = header.title
        if (
            precise
            and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", canonical_minute)
            and precise[:16] == canonical_minute
        ):
            local_header = _entry_headers(block)[0]
            block = (
                block[:local_header.start]
                + f"## {precise}"
                + block[local_header.end:]
            )
        if (
            isinstance(document.get("synthesized"), bool)
            and not _SYNTHESIZED.search(block)
        ):
            value = "true" if document["synthesized"] else "false"
            rendered = f"{'Synthesized:'.ljust(17)}{value}"
            id_line = _ENTRY_ID.search(block)
            if id_line:
                newline = "\r\n" if "\r\n" in block else "\n"
                block = (
                    block[:id_line.end()]
                    + newline
                    + rendered
                    + block[id_line.end():]
                )
        output.append(block)
    return "".join(output)


def _enrich_markdown_scan(markdown: MarkdownScan, elasticsearch: ElasticsearchScan) -> MarkdownScan:
    documents = {change.entry_id: change.document for change in elasticsearch.changes}
    return MarkdownScan(
        tuple(MarkdownFileChange(
            path=change.path,
            original_text=change.original_text,
            updated_text=enrich_markdown_metadata(change.updated_text, documents),
            changes=change.changes,
            identity=change.identity,
        ) for change in markdown.changes),
        markdown.unresolved_ids,
        markdown.source_counts,
        markdown.entry_sources,
    )


class ElasticsearchClient(_BaseElasticsearchClient):
    def scan_media(
        self,
        index: str,
        source_renames: Mapping[str, str] | None = None,
    ) -> ElasticsearchScan:
        from urllib.parse import quote

        encoded = quote(index, safe="-_.")
        response = self._request(
            "POST", f"/{encoded}/_search?scroll=1m",
            {"size": 500, "sort": ["_doc"], "seq_no_primary_term": True,
             "query": {"match_all": {}}},
        )
        if not isinstance(response, dict):
            raise RuntimeError("Elasticsearch returned a malformed search response.")
        total = response.get("hits", {}).get("total")
        if isinstance(total, dict):
            if total.get("relation") != "eq":
                raise RuntimeError("Elasticsearch search total is not exact.")
            expected_hits = int(total.get("value") or 0)
        elif isinstance(total, int):
            expected_hits = total
        else:
            raise RuntimeError("Elasticsearch search response omitted an exact hit total.")
        scroll_id = str(response.get("_scroll_id") or "")
        changes: list[ElasticsearchChange] = []
        unresolved: list[str] = []
        seen_entry_ids: dict[str, str] = {}
        entry_sources: dict[str, str] = {}
        observed_hits = 0
        try:
            while True:
                if response.get("timed_out") is True:
                    raise RuntimeError("Elasticsearch search timed out.")
                shards = response.get("_shards")
                if isinstance(shards, dict) and int(shards.get("failed") or 0):
                    raise RuntimeError("Elasticsearch search had failed shards.")
                hits = response.get("hits", {}).get("hits", [])
                if not isinstance(hits, list):
                    raise RuntimeError("Elasticsearch returned malformed search hits.")
                if not hits:
                    break
                observed_hits += len(hits)
                for hit in hits:
                    if not isinstance(hit, dict):
                        raise RuntimeError("Elasticsearch returned a malformed hit.")
                    source = hit.get("_source")
                    if not isinstance(source, dict):
                        raise RuntimeError("Elasticsearch hit omitted a valid _source.")
                    if not hit.get("_id") or not hit.get("_index"):
                        raise RuntimeError("Elasticsearch hit omitted document identity.")
                    current_source_value = source.get("source")
                    if not isinstance(current_source_value, str) or not current_source_value.strip():
                        raise RuntimeError("Elasticsearch HFL document omitted a valid source.")
                    doc_id = str(hit.get("_id") or "")
                    entry_id = _canonical_entry_id(str(source.get("entry_id") or doc_id))
                    current_source = str(source.get("source", "")).strip()
                    if previous := seen_entry_ids.get(entry_id):
                        raise RuntimeError(
                            f"Duplicate Elasticsearch HFL entry ID {entry_id} "
                            f"in documents {previous} and {doc_id}."
                        )
                    seen_entry_ids[entry_id] = doc_id
                    entry_sources[entry_id] = current_source
                    if source_renames is None:
                        if current_source.casefold() != "media":
                            continue
                        references = source.get("references")
                        new_source = classify_references(
                            str(item) for item in references
                        ) if isinstance(references, list) else None
                    else:
                        if current_source not in source_renames:
                            continue
                        new_source = source_renames[current_source]
                    if new_source is None:
                        unresolved.append(entry_id)
                        continue
                    if "_seq_no" not in hit or "_primary_term" not in hit:
                        raise RuntimeError(
                            "Elasticsearch concurrency metadata missing for "
                            f"{entry_id}."
                        )
                    changes.append(ElasticsearchChange(
                        index=str(hit.get("_index") or index), doc_id=doc_id,
                        entry_id=entry_id, old_source=current_source,
                        new_source=new_source,
                        document=copy.deepcopy(source),
                        seq_no=(int(hit["_seq_no"]) if "_seq_no" in hit else None),
                        primary_term=(
                            int(hit["_primary_term"])
                            if "_primary_term" in hit else None
                        ),
                    ))
                if not scroll_id:
                    break
                response = self._request("POST", "/_search/scroll", {"scroll": "1m", "scroll_id": scroll_id})
                if not isinstance(response, dict):
                    raise RuntimeError("Elasticsearch returned a malformed scroll response.")
                scroll_id = str(response.get("_scroll_id") or scroll_id)
        finally:
            if scroll_id:
                try:
                    self._request("DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})
                except RuntimeError:
                    pass
        if observed_hits != expected_hits:
            raise RuntimeError(
                "Elasticsearch scan was incomplete: "
                f"expected {expected_hits} hits, observed {observed_hits}."
            )
        return ElasticsearchScan(tuple(changes), tuple(unresolved), entry_sources)

    def verify_updated_documents(
        self,
        changes: Iterable[ElasticsearchChange],
    ) -> None:
        pending = tuple(changes)
        if not pending:
            return
        response = self._request(
            "POST",
            "/_mget",
            {"docs": [
                {"_index": change.index, "_id": change.doc_id}
                for change in pending
            ]},
        )
        documents = response.get("docs") if isinstance(response, dict) else None
        if not isinstance(documents, list) or len(documents) != len(pending):
            raise RuntimeError("Elasticsearch postflight returned malformed documents.")
        by_key = {
            (str(document.get("_index") or ""), str(document.get("_id") or "")): document
            for document in documents
            if isinstance(document, dict)
        }
        for change in pending:
            document = by_key.get((change.index, change.doc_id))
            source = document.get("_source") if isinstance(document, dict) else None
            if not isinstance(source, dict):
                raise RuntimeError(
                    f"Elasticsearch postflight omitted {change.entry_id}."
                )
            expected = copy.deepcopy(change.document)
            expected["source"] = change.new_source
            if source != expected:
                raise RuntimeError(
                    f"Elasticsearch postflight mismatch for {change.entry_id}."
                )

    def verify_restored_documents(
        self,
        changes: Iterable[ElasticsearchChange],
    ) -> None:
        """Fail if rollback did not restore every original `_source` byte-value."""
        pending = tuple(changes)
        if not pending:
            return
        response = self._request(
            "POST",
            "/_mget",
            {"docs": [
                {"_index": change.index, "_id": change.doc_id}
                for change in pending
            ]},
        )
        documents = response.get("docs") if isinstance(response, dict) else None
        if not isinstance(documents, list) or len(documents) != len(pending):
            raise RuntimeError("Elasticsearch rollback verification was malformed.")
        by_key = {
            (str(document.get("_index") or ""), str(document.get("_id") or "")): document
            for document in documents
            if isinstance(document, dict)
        }
        unresolved: list[str] = []
        for change in pending:
            document = by_key.get((change.index, change.doc_id))
            source = document.get("_source") if isinstance(document, dict) else None
            if source != change.document:
                unresolved.append(change.entry_id)
        if unresolved:
            raise RuntimeError(
                "manual recovery required for Elasticsearch documents: "
                + ", ".join(sorted(unresolved))
            )

    def _reconcile_batch(
        self,
        batch: tuple[ElasticsearchChange, ...],
        *,
        restore: bool,
    ) -> tuple[ElasticsearchChange, ...]:
        response = self._request(
            "POST",
            "/_mget",
            {"docs": [
                {"_index": change.index, "_id": change.doc_id, "_source": ["source"]}
                for change in batch
            ]},
        )
        documents = response.get("docs") if isinstance(response, dict) else None
        if not isinstance(documents, list):
            raise BulkUpdateError(
                "Elasticsearch batch reconciliation returned a malformed response."
            )
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for document in documents:
            if not isinstance(document, dict):
                continue
            by_key[(str(document.get("_index") or ""), str(document.get("_id") or ""))] = document
        applied: list[ElasticsearchChange] = []
        unresolved: list[str] = []
        for change in batch:
            document = by_key.get((change.index, change.doc_id))
            source = document.get("_source") if isinstance(document, dict) else None
            current = str(source.get("source", "")) if isinstance(source, dict) else ""
            target = change.old_source if restore else change.new_source
            untouched = change.new_source if restore else change.old_source
            if current == target:
                applied.append(change)
            elif current != untouched:
                unresolved.append(change.entry_id)
        if unresolved:
            raise BulkUpdateError(
                "Elasticsearch batch reconciliation found missing or unexpected "
                "source state for " + ", ".join(sorted(unresolved)) + ".",
                tuple(applied),
            )
        return tuple(applied)

    def update_sources(
        self,
        changes: Iterable[ElasticsearchChange],
        *,
        restore: bool = False,
    ) -> tuple[ElasticsearchChange, ...]:
        pending = tuple(changes)
        applied: list[ElasticsearchChange] = []

        def fail_after_reconciliation(
            batch: tuple[ElasticsearchChange, ...],
            message: str,
            cause: Exception | None = None,
        ) -> Never:
            try:
                reconciled = self._reconcile_batch(batch, restore=restore)
            except BulkUpdateError as exc:
                raise BulkUpdateError(
                    message + " Reconciliation did not prove every attempted item; "
                    "all attempted items require conditional compensation.",
                    tuple(applied) + batch,
                ) from (cause or exc)
            except Exception as exc:
                raise BulkUpdateError(
                    message + " Reconciliation failed; all attempted items require "
                    "conditional compensation.",
                    tuple(applied) + batch,
                ) from (cause or exc)
            raise BulkUpdateError(
                message + " Attempted batch state was reconciled.",
                tuple(applied) + reconciled,
            ) from cause

        for offset in range(0, len(pending), 250):
            batch = pending[offset:offset + 250]
            lines: list[str] = []
            for change in batch:
                action: dict[str, Any] = {
                    "_index": change.index,
                    "_id": change.doc_id,
                }
                if restore:
                    action["retry_on_conflict"] = 3
                elif change.seq_no is None or change.primary_term is None:
                    raise BulkUpdateError(
                        "Elasticsearch concurrency metadata missing for source update.",
                        tuple(applied),
                    )
                else:
                    action["if_seq_no"] = change.seq_no
                    action["if_primary_term"] = change.primary_term
                lines.append(json.dumps(
                    {"update": action}, separators=(",", ":")
                ))
                if restore:
                    body = {"script": {
                        "lang": "painless",
                        "source": (
                            "if (ctx._source.source == params.current) { "
                            "ctx._source.source = params.original; "
                            "} else if (ctx._source.source != params.original) { "
                            "throw new IllegalStateException('unexpected source'); }"
                        ),
                        "params": {
                            "current": change.new_source,
                            "original": change.old_source,
                        },
                    }}
                else:
                    body = {"doc": {"source": change.new_source}}
                lines.append(json.dumps(body, separators=(",", ":")))
            if not lines:
                continue
            try:
                response = self._request(
                    "POST", "/_bulk",
                    raw_body=("\n".join(lines) + "\n").encode("utf-8"),
                    content_type="application/x-ndjson",
                )
            except Exception as exc:
                fail_after_reconciliation(
                    batch, "Elasticsearch bulk transport failed.", exc,
                )
            if not isinstance(response, dict):
                fail_after_reconciliation(
                    batch, "Elasticsearch returned a malformed bulk response.",
                )
            items = response.get("items")
            if not isinstance(items, list):
                fail_after_reconciliation(
                    batch, "Elasticsearch returned a malformed bulk response.",
                )
            batch_failed = False
            malformed_item = False
            batch_applied: list[ElasticsearchChange] = []
            for change, item in zip(batch, items):
                try:
                    result = item["update"]
                    if not isinstance(result, dict):
                        raise TypeError("bulk update result is not an object")
                    status = int(result.get("status") or 0)
                except (KeyError, TypeError, ValueError):
                    malformed_item = True
                    continue
                if 200 <= status < 300 and not result.get("error"):
                    batch_applied.append(change)
                else:
                    batch_failed = True
            if len(items) != len(batch) or malformed_item:
                fail_after_reconciliation(
                    batch, "Elasticsearch returned an incomplete or malformed bulk response.",
                )
            if response.get("errors") or batch_failed:
                fail_after_reconciliation(
                    batch, "Elasticsearch rejected one or more source updates.",
                )
            applied.extend(batch_applied)
        return tuple(applied)


def elasticsearch_client_from_env() -> ElasticsearchClient:
    base = _base_client_from_env()
    return ElasticsearchClient(base.base_url, headers=base.headers, timeout=base.timeout)


def _copy_file_metadata(source_fd: int, target_fd: int) -> None:
    copyfile_library = ctypes.CDLL(None, use_errno=True)
    fcopyfile = getattr(copyfile_library, "fcopyfile", None)
    if fcopyfile is None:
        raise RuntimeError("Filesystem metadata copying is unavailable; refusing apply.")
    fcopyfile.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    fcopyfile.restype = ctypes.c_int
    transient = {getattr(errno, "ENOATTR", 93), getattr(errno, "ENODATA", 61), errno.ENOTSUP}
    copied = False
    last_error = 0
    for flags in (0x00000007, 0x00000003, 0x00000002):
        if fcopyfile(source_fd, target_fd, None, flags) == 0:
            copied = True
            break
        last_error = ctypes.get_errno()
        if last_error not in transient:
            raise OSError(last_error, os.strerror(last_error))
    if not copied:
        raise OSError(last_error, os.strerror(last_error))

    source_xattrs = _xattrs_base64(source_fd)
    if source_xattrs:
        fsetxattr = copyfile_library.fsetxattr
        fsetxattr.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        fsetxattr.restype = ctypes.c_int
        for name, encoded in source_xattrs.items():
            raw_name = name.encode("utf-8", errors="surrogateescape")
            value = base64.b64decode(encoded)
            value_buffer = ctypes.create_string_buffer(value)
            if fsetxattr(
                target_fd, raw_name, value_buffer, len(value), 0, 0,
            ) != 0:
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error))

    class AttrList(ctypes.Structure):
        _fields_ = [
            ("bitmapcount", ctypes.c_ushort),
            ("reserved", ctypes.c_uint16),
            ("commonattr", ctypes.c_uint32),
            ("volattr", ctypes.c_uint32),
            ("dirattr", ctypes.c_uint32),
            ("fileattr", ctypes.c_uint32),
            ("forkattr", ctypes.c_uint32),
        ]

    class TimeSpec(ctypes.Structure):
        _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]

    birthtime_ns = int(getattr(os.fstat(source_fd), "st_birthtime", 0) * 1_000_000_000)
    attributes = AttrList(bitmapcount=5, commonattr=0x00000200)
    timestamp = TimeSpec(
        tv_sec=birthtime_ns // 1_000_000_000,
        tv_nsec=birthtime_ns % 1_000_000_000,
    )
    fsetattrlist = getattr(ctypes.CDLL(None, use_errno=True), "fsetattrlist", None)
    if fsetattrlist is None:
        raise RuntimeError("Birthtime preservation is unavailable; refusing apply.")
    fsetattrlist.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(AttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint,
    ]
    fsetattrlist.restype = ctypes.c_int
    if fsetattrlist(
        target_fd,
        ctypes.byref(attributes),
        ctypes.byref(timestamp),
        ctypes.sizeof(timestamp),
        0,
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _write_temp_at(
    name: str,
    text: str,
    *,
    mode: int,
    dir_fd: int,
    metadata_source: str,
) -> tuple[int, int, int, int, int]:
    source_fd = os.open(
        metadata_source,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=dir_fd,
    )
    created = False
    try:
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=dir_fd,
            )
            created = True
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                _copy_file_metadata(source_fd, handle.fileno())
                os.fchmod(handle.fileno(), mode)
                source_metadata = _backup_metadata(source_fd)
                target_metadata = _backup_metadata(handle.fileno())
                if target_metadata != source_metadata:
                    differences = sorted(
                        key for key in source_metadata
                        if target_metadata.get(key) != source_metadata.get(key)
                    )
                    raise RuntimeError(
                        "Markdown filesystem metadata was not preserved: "
                        + ", ".join(differences)
                    )
                os.fsync(handle.fileno())
            return _file_identity(
                os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            )
        except Exception:
            if created:
                os.unlink(name, dir_fd=dir_fd)
                os.fsync(dir_fd)
            raise
    finally:
        os.close(source_fd)


def _write_fd_payload(file_fd: int, payload: bytes) -> None:
    os.lseek(file_fd, 0, os.SEEK_SET)
    written = 0
    while written < len(payload):
        count = os.write(file_fd, payload[written:])
        if count <= 0:
            raise OSError("Short write while publishing HFL Markdown.")
        written += count
    os.ftruncate(file_fd, len(payload))
    os.fsync(file_fd)


def _offline_in_place_write(
    path: Path,
    text: str,
    *,
    dir_fd: int,
    mode: int = 0o600,
    expected_text: str,
    expected_identity: tuple[int, int, int, int, int],
) -> tuple[int, int, int, int, int]:
    """Write through the retained inode while the corpus-wide lock is held.

    ExFAT cannot publish a replacement inode without losing exact creation-time
    precision. The transaction backup is the crash-recovery artifact; this helper
    performs immediate byte rollback for every caught failure.
    """
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    file_fd = os.open(path.name, flags, dir_fd=dir_fd)
    publication_started = False
    retained_stat: os.stat_result | None = None
    original_metadata: dict[str, Any] | None = None
    try:
        retained_stat = os.fstat(file_fd)
        if _file_identity(retained_stat) != expected_identity:
            raise RuntimeError(f"HFL file changed before offline write: {path.name}.")
        original_metadata = _backup_metadata(file_fd)
        current = os.pread(file_fd, retained_stat.st_size, 0).decode("utf-8")
        os.utime(
            file_fd,
            ns=(original_metadata["atime_ns"], original_metadata["mtime_ns"]),
        )
        if current != expected_text:
            raise RuntimeError(f"HFL file content changed before offline write: {path.name}.")

        publication_started = True
        _write_fd_payload(file_fd, text.encode("utf-8"))
        os.utime(
            file_fd,
            ns=(original_metadata["atime_ns"], original_metadata["mtime_ns"]),
        )
        published_stat = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
        published_identity = _file_identity(published_stat)
        if (published_stat.st_dev, published_stat.st_ino) != (
            retained_stat.st_dev, retained_stat.st_ino,
        ):
            raise RuntimeError(f"HFL path changed during offline write: {path.name}.")
        observed, _ = _read_markdown_exact(
            path, published_identity, dir_fd=dir_fd,
        )
        os.utime(
            file_fd,
            ns=(original_metadata["atime_ns"], original_metadata["mtime_ns"]),
        )
        if observed != text:
            raise RuntimeError(f"Offline publication verification failed for {path.name}.")
        final_metadata = _backup_metadata(file_fd)
        if final_metadata != original_metadata:
            differences = sorted(
                key for key in original_metadata
                if final_metadata.get(key) != original_metadata[key]
            )
            raise RuntimeError(
                "Offline publication changed filesystem metadata: "
                + ", ".join(differences)
            )
        final_stat = os.fstat(file_fd)
        canonical_stat = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
        if (canonical_stat.st_dev, canonical_stat.st_ino) != (
            final_stat.st_dev, final_stat.st_ino,
        ):
            raise RuntimeError(f"HFL path changed after offline write: {path.name}.")
        return _file_identity(final_stat)
    except Exception as exc:
        if publication_started and original_metadata is not None and retained_stat is not None:
            try:
                _write_fd_payload(file_fd, expected_text.encode("utf-8"))
                os.utime(
                    file_fd,
                    ns=(original_metadata["atime_ns"], original_metadata["mtime_ns"]),
                )
                restored_stat = os.fstat(file_fd)
                restored = os.pread(file_fd, restored_stat.st_size, 0).decode("utf-8")
                if restored != expected_text:
                    raise RuntimeError("restored bytes differ from expected bytes")
                os.utime(
                    file_fd,
                    ns=(original_metadata["atime_ns"], original_metadata["mtime_ns"]),
                )
                if _backup_metadata(file_fd) != original_metadata:
                    raise RuntimeError("restored filesystem metadata differs")
            except Exception as rollback_exc:
                raise RuntimeError(
                    f"Offline write failed for {path.name}; immediate rollback failed: "
                    f"{rollback_exc}."
                ) from exc
            try:
                canonical_stat = os.stat(
                    path.name, dir_fd=dir_fd, follow_symlinks=False,
                )
            except OSError:
                canonical_stat = None
            if canonical_stat is None or (
                canonical_stat.st_dev, canonical_stat.st_ino,
            ) != (retained_stat.st_dev, retained_stat.st_ino):
                raise RuntimeError(
                    f"Offline write failed for {path.name}; retained inode was restored "
                    "but the canonical path changed. Use the recovery backup to restore "
                    "the canonical path."
                ) from exc
        raise
    finally:
        os.close(file_fd)


def _swap_names(dir_fd: int, first: str, second: str) -> None:
    renameatx_np = getattr(ctypes.CDLL(None, use_errno=True), "renameatx_np", None)
    if renameatx_np is None:
        raise RuntimeError("Atomic filesystem exchange is unavailable; refusing apply.")
    renameatx_np.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameatx_np.restype = ctypes.c_int
    if renameatx_np(
        dir_fd,
        os.fsencode(first),
        dir_fd,
        os.fsencode(second),
        0x00000002,
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), second)


def _guarded_atomic_write(
    path: Path,
    text: str,
    *,
    mode: int,
    dir_fd: int,
    expected_text: str,
    expected_identity: tuple[int, int, int, int, int],
) -> tuple[int, int, int, int, int]:
    original_stat = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
    original_times = (original_stat.st_atime_ns, original_stat.st_mtime_ns)
    nonce = f"{os.getpid()}-{uuid.uuid4().hex}"
    guard_name = f".{path.name}.guard-{nonce}"
    temporary_name = f".{path.name}.tmp-{nonce}"
    os.link(
        path.name,
        guard_name,
        src_dir_fd=dir_fd,
        dst_dir_fd=dir_fd,
        follow_symlinks=False,
    )
    guard_path = Path(guard_name)
    temporary_path = Path(temporary_name)
    guard_exists = True
    temporary_exists = False
    swapped = False
    try:
        current, _identity = _read_markdown_exact(
            guard_path,
            expected_identity,
            dir_fd=dir_fd,
        )
        if current != expected_text:
            raise RuntimeError(f"Concurrent HFL corpus change detected for {path.name}.")
        published_identity = _write_temp_at(
            temporary_name,
            text,
            mode=mode,
            dir_fd=dir_fd,
            metadata_source=guard_name,
        )
        temporary_exists = True
        _swap_names(dir_fd, temporary_name, path.name)
        swapped = True
        try:
            os.fsync(dir_fd)
            displaced, _identity = _read_markdown_exact(
                temporary_path,
                expected_identity,
                dir_fd=dir_fd,
            )
            guarded, _identity = _read_markdown_exact(
                guard_path,
                expected_identity,
                dir_fd=dir_fd,
            )
            published, _identity = _read_markdown_exact(
                path,
                published_identity,
                dir_fd=dir_fd,
            )
            if displaced != expected_text or guarded != expected_text or published != text:
                raise RuntimeError(
                    f"Concurrent HFL corpus change detected for {path.name}."
                )
            os.unlink(temporary_name, dir_fd=dir_fd)
            temporary_exists = False
            os.fsync(dir_fd)
            os.unlink(guard_name, dir_fd=dir_fd)
            guard_exists = False
            swapped = False
            os.utime(
                path.name, ns=original_times, dir_fd=dir_fd,
                follow_symlinks=False,
            )
            os.fsync(dir_fd)
            return published_identity
        except Exception:
            published, _identity = _read_markdown_exact(
                path,
                published_identity,
                dir_fd=dir_fd,
            )
            if published != text:
                raise RuntimeError(
                    f"Migration no longer owns published file {path.name}; "
                    f"recovery artifacts retained as {guard_name} and {temporary_name}."
                )
            recovery_name = temporary_name if temporary_exists else guard_name
            _swap_names(dir_fd, recovery_name, path.name)
            swapped = False
            os.fsync(dir_fd)
            os.utime(
                path.name, ns=original_times, dir_fd=dir_fd,
                follow_symlinks=False,
            )
            if recovery_name == temporary_name:
                temporary_exists = True
            else:
                guard_exists = True
            raise
    finally:
        if not swapped:
            cleaned = False
            if temporary_exists:
                try:
                    os.unlink(temporary_name, dir_fd=dir_fd)
                    cleaned = True
                except FileNotFoundError:
                    pass
            if guard_exists:
                try:
                    os.unlink(guard_name, dir_fd=dir_fd)
                    cleaned = True
                except FileNotFoundError:
                    pass
            if cleaned:
                os.fsync(dir_fd)


def _verify_directory_binding(path: Path, descriptor: int) -> None:
    current = os.stat(path, follow_symlinks=False)
    retained = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(current.st_mode)
        or (current.st_dev, current.st_ino) != (retained.st_dev, retained.st_ino)
    ):
        raise RuntimeError("HFL corpus root changed during migration.")


def _write_bytes_fsync_at(
    descriptor: int,
    name: str,
    payload: bytes,
    *,
    mode: int = 0o600,
) -> None:
    file_fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
        dir_fd=descriptor,
    )
    try:
        os.fchmod(file_fd, mode)
        with os.fdopen(file_fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(file_fd)
    finally:
        os.close(file_fd)
    os.fsync(descriptor)


def _acl_text(file_fd: int) -> str | None:
    libc = ctypes.CDLL(None, use_errno=True)
    acl_get_fd_np = getattr(libc, "acl_get_fd_np", None)
    acl_to_text = getattr(libc, "acl_to_text", None)
    acl_free = getattr(libc, "acl_free", None)
    if acl_get_fd_np is None or acl_to_text is None or acl_free is None:
        return None
    acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    acl_get_fd_np.restype = ctypes.c_void_p
    acl_to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
    acl_to_text.restype = ctypes.c_void_p
    acl_free.argtypes = [ctypes.c_void_p]
    acl_free.restype = ctypes.c_int
    acl = acl_get_fd_np(file_fd, 0x00000100)
    if not acl:
        error = ctypes.get_errno()
        if error in {0, errno.ENOENT}:
            return None
        raise OSError(error, os.strerror(error))
    text_pointer: int | None = None
    try:
        length = ctypes.c_ssize_t()
        text_pointer = acl_to_text(acl, ctypes.byref(length))
        if not text_pointer:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return ctypes.string_at(text_pointer, length.value).decode(
            "utf-8", errors="surrogateescape",
        )
    finally:
        if text_pointer:
            acl_free(text_pointer)
        acl_free(acl)


def _xattrs_base64(file_fd: int) -> dict[str, str]:
    libc = ctypes.CDLL(None, use_errno=True)
    flistxattr = libc.flistxattr
    fgetxattr = libc.fgetxattr
    flistxattr.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
    ]
    flistxattr.restype = ctypes.c_ssize_t
    fgetxattr.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    fgetxattr.restype = ctypes.c_ssize_t
    transient = {getattr(errno, "ENOATTR", 93), getattr(errno, "ENODATA", 61), errno.ERANGE}
    last_retrievable: dict[str, str] = {}
    for _attempt in range(5):
        size = flistxattr(file_fd, None, 0, 0)
        if size < 0:
            error = ctypes.get_errno()
            if error in transient:
                continue
            raise OSError(error, os.strerror(error))
        if size == 0:
            return {}
        names_buffer = ctypes.create_string_buffer(size)
        observed_size = flistxattr(file_fd, names_buffer, size, 0)
        if observed_size != size:
            error = ctypes.get_errno()
            if observed_size < 0 and error not in transient:
                raise OSError(error, os.strerror(error))
            continue
        values: dict[str, str] = {}
        retry = False
        for raw_name in names_buffer.raw[:size].split(b"\0"):
            if not raw_name:
                continue
            value_size = fgetxattr(file_fd, raw_name, None, 0, 0, 0)
            if value_size < 0:
                error = ctypes.get_errno()
                if error in transient:
                    retry = True
                    break
                raise OSError(error, os.strerror(error))
            value_buffer = ctypes.create_string_buffer(value_size)
            if value_size and fgetxattr(
                file_fd, raw_name, value_buffer, value_size, 0, 0,
            ) != value_size:
                error = ctypes.get_errno()
                if error in transient:
                    retry = True
                    break
                raise OSError(error, os.strerror(error))
            name = raw_name.decode("utf-8", errors="surrogateescape")
            values[name] = base64.b64encode(
                value_buffer.raw[:value_size],
            ).decode("ascii")
        if not retry:
            return values
        last_retrievable = values
    # ExFAT can permanently advertise an AppleDouble-backed name whose value is
    # unavailable through fgetxattr. The separately backed-up AppleDouble bytes
    # are authoritative for recovery; retain and compare every retrievable xattr.
    return last_retrievable


def _backup_metadata(
    file_fd: int,
    *,
    opaque_appledouble: bool = False,
) -> dict[str, Any]:
    info = os.fstat(file_fd)
    metadata = {
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "atime_ns": info.st_atime_ns,
        "mtime_ns": info.st_mtime_ns,
        "birthtime_ns": int(getattr(info, "st_birthtime", 0) * 1_000_000_000),
        "flags": int(getattr(info, "st_flags", 0)),
        "acl": None if opaque_appledouble else _acl_text(file_fd),
        "xattrs_base64": {} if opaque_appledouble else _xattrs_base64(file_fd),
    }
    if opaque_appledouble:
        metadata["opaque_appledouble"] = True
    return metadata


def _open_or_create_private_directory(
    path: Path,
    *,
    exist_ok: bool,
) -> tuple[Path, int]:
    absolute = Path(os.path.abspath(Path(path).expanduser()))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("/", flags)
    try:
        for index, part in enumerate(absolute.parts[1:], start=1):
            final = index == len(absolute.parts) - 1
            created = False
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
                os.fchmod(child, 0o700)
                created = True
            if final and not created and not exist_ok:
                os.close(child)
                raise FileExistsError(absolute)
            os.close(descriptor)
            descriptor = child
        os.fchmod(descriptor, 0o700)
        return absolute, descriptor
    except Exception:
        os.close(descriptor)
        raise


def _create_private_child(parent_fd: int, name: str) -> int:
    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    os.fsync(parent_fd)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    os.fchmod(descriptor, 0o700)
    return descriptor


def _open_or_create_private_child(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return _create_private_child(parent_fd, name)
    except FileExistsError:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise RuntimeError(f"Backup component is not a directory: {name}.")
        return descriptor


def _create_backup(
    corpus_root: Path,
    markdown: MarkdownScan,
    elasticsearch: ElasticsearchScan,
    backup_root: Path,
    *,
    corpus_fd: int | None = None,
    retain_descriptor: bool = False,
) -> Path | tuple[Path, int]:
    if corpus_fd is None:
        raise RuntimeError("A retained corpus directory descriptor is required.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root_path, backup_root_fd = _open_or_create_private_directory(
        backup_root, exist_ok=True,
    )
    target_name = f"{stamp}-{uuid.uuid4().hex[:8]}"
    target = backup_root_path / target_name
    target_fd: int | None = None
    files_fd: int | None = None
    appledouble_fd: int | None = None
    try:
        target_fd = _create_private_child(backup_root_fd, target_name)
        files_fd = _create_private_child(target_fd, "markdown")
        appledouble_fd = _create_private_child(target_fd, "appledouble")
        markdown_hashes: dict[str, str] = {}
        markdown_metadata: dict[str, dict[str, Any]] = {}
        appledouble_hashes: dict[str, str] = {}
        appledouble_metadata: dict[str, dict[str, Any]] = {}
        for change in markdown.changes:
            relative = change.path.relative_to(corpus_root)
            with _change_parent_directory(
                corpus_root, corpus_fd, change.path,
            ) as (_relative, source_parent_fd):
                current, _identity = _read_markdown_exact(
                    Path(relative.name),
                    change.identity,
                    dir_fd=source_parent_fd,
                )
                source_file_fd = os.open(
                    relative.name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=source_parent_fd,
                )
                try:
                    markdown_metadata[str(relative)] = _backup_metadata(source_file_fd)
                finally:
                    os.close(source_file_fd)
                sidecar_name = f"._{relative.name}"
                try:
                    sidecar_fd = os.open(
                        sidecar_name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=source_parent_fd,
                    )
                except FileNotFoundError:
                    sidecar_payload = None
                else:
                    sidecar_times: tuple[int, int] | None = None
                    try:
                        sidecar_stat = os.fstat(sidecar_fd)
                        if not stat.S_ISREG(sidecar_stat.st_mode):
                            raise RuntimeError(
                                f"AppleDouble sidecar is not a regular file: {sidecar_name}."
                            )
                        sidecar_times = (
                            sidecar_stat.st_atime_ns,
                            sidecar_stat.st_mtime_ns,
                        )
                        appledouble_metadata[str(relative)] = _backup_metadata(
                            sidecar_fd, opaque_appledouble=True,
                        )
                        chunks: list[bytes] = []
                        while True:
                            chunk = os.read(sidecar_fd, 1024 * 1024)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        sidecar_payload = b"".join(chunks)
                    finally:
                        if sidecar_times is not None:
                            os.utime(sidecar_fd, ns=sidecar_times)
                        os.close(sidecar_fd)
                _verify_directory_binding(
                    corpus_root / relative.parent, source_parent_fd,
                )
            if current != change.original_text:
                raise RuntimeError(
                    f"Concurrent HFL corpus change detected for {change.path.name}."
                )
            payload = change.original_text.encode("utf-8")
            destination_fd = os.dup(files_fd)
            try:
                for part in relative.parent.parts:
                    child_fd = _open_or_create_private_child(destination_fd, part)
                    os.close(destination_fd)
                    destination_fd = child_fd
                _write_bytes_fsync_at(destination_fd, relative.name, payload)
            finally:
                os.close(destination_fd)
            markdown_hashes[str(relative)] = hashlib.sha256(payload).hexdigest()
            if sidecar_payload is not None:
                destination_fd = os.dup(appledouble_fd)
                try:
                    for part in relative.parent.parts:
                        child_fd = _open_or_create_private_child(destination_fd, part)
                        os.close(destination_fd)
                        destination_fd = child_fd
                    _write_bytes_fsync_at(destination_fd, sidecar_name, sidecar_payload)
                finally:
                    os.close(destination_fd)
                appledouble_hashes[str(relative)] = hashlib.sha256(
                    sidecar_payload,
                ).hexdigest()
        es_payload = b"".join(
            (
                json.dumps({
                    "_index": change.index, "_id": change.doc_id,
                    "_source": change.document,
                }, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            for change in elasticsearch.changes
        )
        _write_bytes_fsync_at(target_fd, "elasticsearch.ndjson", es_payload)
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "markdown_files": len(markdown.changes),
            "markdown_entries": sum(
                len(change.changes) for change in markdown.changes
            ),
            "elasticsearch_documents": len(elasticsearch.changes),
            "unresolved_markdown": list(markdown.unresolved_ids),
            "unresolved_elasticsearch": list(elasticsearch.unresolved_ids),
            "source_counts": markdown.source_counts,
            "markdown_sha256": markdown_hashes,
            "markdown_metadata": markdown_metadata,
            "appledouble_sha256": appledouble_hashes,
            "appledouble_metadata": appledouble_metadata,
            "elasticsearch_ndjson_sha256": hashlib.sha256(es_payload).hexdigest(),
            "entry_ids": sorted({
                source.entry_id
                for change in markdown.changes
                for source in change.changes
            }.union(change.entry_id for change in elasticsearch.changes)),
        }
        _write_bytes_fsync_at(
            target_fd,
            "manifest.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        os.fsync(files_fd)
        os.fsync(appledouble_fd)
        os.fsync(target_fd)
        os.fsync(backup_root_fd)
        _verify_directory_binding(target, target_fd)
        if retain_descriptor:
            return target, os.dup(target_fd)
        return target
    finally:
        if files_fd is not None:
            os.close(files_fd)
        if appledouble_fd is not None:
            os.close(appledouble_fd)
        if target_fd is not None:
            os.close(target_fd)
        os.close(backup_root_fd)


@contextmanager
def _markdown_locks(
    corpus_root: Path,
    changes: Iterable[MarkdownFileChange],
    *,
    corpus_fd: int | None = None,
):
    owned_fd = corpus_fd is None
    if corpus_fd is None:
        _root, corpus_fd = _open_directory_no_follow(corpus_root)
    if corpus_fd is None:
        raise RuntimeError("A retained corpus directory descriptor is required.")
    lock_fd: int | None = None
    lock_descriptors: list[int] = []
    try:
        try:
            os.mkdir(".locks", mode=0o700, dir_fd=corpus_fd)
            os.fsync(corpus_fd)
        except FileExistsError:
            pass
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        lock_fd = os.open(".locks", flags, dir_fd=corpus_fd)
        pending = tuple(sorted(changes, key=lambda change: str(change.path)))
        for lock_name in sorted({f"{change.path.name}.lock" for change in pending}):
            descriptor = os.open(
                lock_name,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=lock_fd,
            )
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        os.close(descriptor)
                        raise TimeoutError(f"Timed out acquiring HFL lock {lock_name}.")
                    time.sleep(0.05)
            lock_descriptors.append(descriptor)
        _verify_directory_binding(corpus_root, corpus_fd)
        yield pending, corpus_fd
    finally:
        for descriptor in reversed(lock_descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        if lock_fd is not None:
            os.close(lock_fd)
        if owned_fd:
            os.close(corpus_fd)


def _write_markdown_changes(
    corpus_root: Path,
    changes: Iterable[MarkdownFileChange],
    *,
    restore: bool = False,
    locks_held: bool = False,
    corpus_fd: int | None = None,
    expected_identities: dict[Path, tuple[int, int, int, int, int]] | None = None,
    offline_replace: bool = False,
) -> dict[Path, tuple[int, int, int, int, int]]:
    if not locks_held:
        pending_input = tuple(changes)
        times = {}
        for change in pending_input:
            info = os.stat(change.path, follow_symlinks=False)
            times[change.path] = (info.st_atime_ns, info.st_mtime_ns)
        try:
            with _markdown_locks(corpus_root, pending_input) as (pending, locked_fd):
                return _write_markdown_changes(
                    corpus_root,
                    pending,
                    restore=restore,
                    locks_held=True,
                    corpus_fd=locked_fd,
                    expected_identities=expected_identities,
                    offline_replace=offline_replace,
                )
        finally:
            active_failure = sys.exc_info()[0] is not None
            for path, file_times in times.items():
                try:
                    os.utime(path, ns=file_times, follow_symlinks=False)
                except (FileNotFoundError, NotADirectoryError):
                    if not active_failure:
                        raise
    if corpus_fd is None:
        raise RuntimeError("A retained corpus directory descriptor is required.")
    pending = tuple(sorted(changes, key=lambda change: str(change.path)))
    written: list[
        tuple[MarkdownFileChange, tuple[int, int, int, int, int], int]
    ] = []

    def ownership(change: MarkdownFileChange) -> tuple[int, int, int, int, int]:
        identity = (
            expected_identities.get(change.path)
            if expected_identities is not None
            else change.identity
        )
        if identity is None:
            raise RuntimeError(f"Missing Markdown ownership state for {change.path.name}.")
        return identity

    def verify(change: MarkdownFileChange) -> None:
        _verify_directory_binding(corpus_root, corpus_fd)
        expected = change.updated_text if restore else change.original_text
        with _change_parent_directory(
            corpus_root, corpus_fd, change.path,
        ) as (relative, parent_fd):
            observed_stat = os.stat(
                relative.name, dir_fd=parent_fd, follow_symlinks=False,
            )
            try:
                current, _identity = _read_markdown_exact(
                    Path(relative.name),
                    ownership(change),
                    dir_fd=parent_fd,
                )
            finally:
                os.utime(
                    relative.name,
                    ns=(observed_stat.st_atime_ns, observed_stat.st_mtime_ns),
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            _verify_directory_binding(corpus_root / relative.parent, parent_fd)
        if current != expected:
            raise RuntimeError(
                f"Concurrent HFL corpus change detected for {change.path.name}."
            )

    try:
        for change in pending:
            verify(change)
        for change in pending:
            verify(change)
            expected_text = change.updated_text if restore else change.original_text
            target_text = change.original_text if restore else change.updated_text
            writer = _offline_in_place_write if offline_replace else _guarded_atomic_write
            with _change_parent_directory(
                corpus_root, corpus_fd, change.path,
            ) as (relative, parent_fd):
                retained_parent_fd = os.dup(parent_fd)
                try:
                    published_identity = writer(
                        Path(relative.name),
                        target_text,
                        mode=change.identity[4],
                        dir_fd=parent_fd,
                        expected_text=expected_text,
                        expected_identity=ownership(change),
                    )
                except Exception:
                    os.close(retained_parent_fd)
                    raise
                written.append((change, published_identity, retained_parent_fd))
                _verify_directory_binding(corpus_root / relative.parent, parent_fd)
            _verify_directory_binding(corpus_root, corpus_fd)
    except Exception as exc:
        rollback_errors: list[str] = []
        for change, published_identity, retained_parent_fd in reversed(written):
            writer = _offline_in_place_write if offline_replace else _guarded_atomic_write
            try:
                writer(
                    Path(change.path.name),
                    change.updated_text if restore else change.original_text,
                    mode=change.identity[4],
                    dir_fd=retained_parent_fd,
                    expected_text=(
                        change.original_text if restore else change.updated_text
                    ),
                    expected_identity=published_identity,
                )
            except Exception as rollback_exc:
                rollback_errors.append(f"{change.path.name}: {rollback_exc}")
            finally:
                os.close(retained_parent_fd)
        if rollback_errors:
            raise RuntimeError(
                f"Markdown publication failed ({exc}); rollback failures: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    result = {change.path: identity for change, identity, _parent_fd in written}
    for _change, _identity, retained_parent_fd in written:
        os.close(retained_parent_fd)
    return result


def _validate_cross_store_sources(
    markdown: MarkdownScan,
    elasticsearch: ElasticsearchScan,
) -> None:
    markdown_sources = {
        source.entry_id: source.new_source
        for change in markdown.changes
        for source in change.changes
    }
    elasticsearch_sources = {
        change.entry_id: change.new_source
        for change in elasticsearch.changes
    }
    markdown_old_sources = {
        source.entry_id: source.old_source
        for change in markdown.changes
        for source in change.changes
    }
    elasticsearch_old_sources = {
        change.entry_id: change.old_source
        for change in elasticsearch.changes
    }
    split_brain_ids = (
        set(markdown_sources).intersection(elasticsearch.unresolved_ids)
        | set(elasticsearch_sources).intersection(markdown.unresolved_ids)
    )
    for entry_id in markdown.unresolved_ids:
        counterpart = elasticsearch.entry_sources.get(entry_id, "")
        if counterpart and counterpart.casefold() != "media":
            split_brain_ids.add(entry_id)
    for entry_id in elasticsearch.unresolved_ids:
        counterpart = markdown.entry_sources.get(entry_id, "")
        if counterpart and counterpart.casefold() != "media":
            split_brain_ids.add(entry_id)
    if split_brain_ids:
        raise RuntimeError(
            "Cross-store unresolved source conflict for "
            + ", ".join(sorted(split_brain_ids))
            + "."
        )
    for entry_id, intended in markdown_sources.items():
        counterpart = elasticsearch.entry_sources.get(entry_id, "")
        allowed = {
            intended.casefold(),
            markdown_old_sources[entry_id].casefold(),
        }
        if counterpart and counterpart.casefold() not in allowed:
            raise RuntimeError(
                f"Cross-store source conflict for {entry_id}: "
                f"Markdown={intended}, Elasticsearch={counterpart}."
            )
    for entry_id, intended in elasticsearch_sources.items():
        counterpart = markdown.entry_sources.get(entry_id, "")
        allowed = {
            intended.casefold(),
            elasticsearch_old_sources[entry_id].casefold(),
        }
        if counterpart and counterpart.casefold() not in allowed:
            raise RuntimeError(
                f"Cross-store source conflict for {entry_id}: "
                f"Markdown={counterpart}, Elasticsearch={intended}."
            )
    for change in elasticsearch.changes:
        markdown_source = markdown_sources.get(change.entry_id)
        if markdown_source and markdown_source != change.new_source:
            raise RuntimeError(
                f"Cross-store source conflict for {change.entry_id}: "
                f"Markdown={markdown_source}, Elasticsearch={change.new_source}."
            )


def _verify_successful_apply(
    corpus: Path,
    corpus_fd: int,
    markdown: MarkdownScan,
    elasticsearch: ElasticsearchScan,
    markdown_identities: Mapping[Path, tuple[int, int, int, int, int]],
    client: Any,
    *,
    index: str,
    source_renames: Mapping[str, str] | None,
) -> None:
    times: dict[Path, tuple[int, int]] = {}
    for change in markdown.changes:
        info = os.stat(change.path, follow_symlinks=False)
        times[change.path] = (info.st_atime_ns, info.st_mtime_ns)
    try:
        _verify_successful_apply_inner(
            corpus, corpus_fd, markdown, elasticsearch,
            markdown_identities, client, index=index,
            source_renames=source_renames,
        )
    finally:
        for path, file_times in times.items():
            os.utime(path, ns=file_times, follow_symlinks=False)


def _verify_successful_apply_inner(
    corpus: Path,
    corpus_fd: int,
    markdown: MarkdownScan,
    elasticsearch: ElasticsearchScan,
    markdown_identities: Mapping[Path, tuple[int, int, int, int, int]],
    client: Any,
    *,
    index: str,
    source_renames: Mapping[str, str] | None,
) -> None:
    for change in markdown.changes:
        with _change_parent_directory(
            corpus, corpus_fd, change.path,
        ) as (relative, parent_fd):
            current, _identity = _read_markdown_exact(
                Path(relative.name),
                markdown_identities[change.path],
                dir_fd=parent_fd,
            )
        if current != change.updated_text:
            raise RuntimeError(
                f"Markdown postflight mismatch for {change.path.name}."
            )
    verifier = getattr(client, "verify_updated_documents", None)
    if not callable(verifier):
        raise RuntimeError("Elasticsearch client lacks postflight document verification.")
    verifier(elasticsearch.changes)
    replay_markdown = scan_markdown(
        corpus, corpus_fd=corpus_fd, source_renames=source_renames,
    )
    replay_elasticsearch = (
        client.scan_media(index)
        if source_renames is None
        else client.scan_media(index, source_renames=source_renames)
    )
    if (
        replay_markdown.changes
        or replay_elasticsearch.changes
        or replay_markdown.unresolved_ids
        or replay_elasticsearch.unresolved_ids
    ):
        raise RuntimeError("Migration postflight was not idempotent.")
    expected_markdown = {
        source.entry_id: source.new_source
        for change in markdown.changes
        for source in change.changes
    }
    expected_elasticsearch = {
        change.entry_id: change.new_source
        for change in elasticsearch.changes
    }
    for entry_id, expected in expected_markdown.items():
        if replay_markdown.entry_sources.get(entry_id) != expected:
            raise RuntimeError(f"Markdown postflight source mismatch for {entry_id}.")
    for entry_id, expected in expected_elasticsearch.items():
        if replay_elasticsearch.entry_sources.get(entry_id) != expected:
            raise RuntimeError(f"Elasticsearch postflight source mismatch for {entry_id}.")
    for entry_id in set(expected_markdown).intersection(expected_elasticsearch):
        if expected_markdown[entry_id] != expected_elasticsearch[entry_id]:
            raise RuntimeError(f"Cross-store postflight mismatch for {entry_id}.")


def _apply_transaction(
    corpus: Path,
    corpus_fd: int,
    locked_changes: tuple[MarkdownFileChange, ...],
    markdown: MarkdownScan,
    elasticsearch: ElasticsearchScan,
    client: Any,
    *,
    index: str,
    source_renames: Mapping[str, str] | None,
    offline_exfat: bool,
    backup_dir: Path,
    backup_fd: int,
) -> None:
    _verify_directory_binding(backup_dir, backup_fd)
    markdown_written = False
    elasticsearch_written = False
    markdown_identities: dict[Path, tuple[int, int, int, int, int]] = {}
    try:
        markdown_identities = _write_markdown_changes(
            corpus,
            locked_changes,
            locks_held=True,
            corpus_fd=corpus_fd,
            offline_replace=offline_exfat,
        )
        markdown_written = True
        client.update_sources(elasticsearch.changes)
        elasticsearch_written = True
        _verify_successful_apply(
            corpus,
            corpus_fd,
            markdown,
            elasticsearch,
            markdown_identities,
            client,
            index=index,
            source_renames=source_renames,
        )
        _verify_directory_binding(backup_dir, backup_fd)
    except Exception as exc:
        if hasattr(exc, "add_note"):
            exc.add_note(f"Recovery backup: {backup_dir}")
        rollback_errors: list[str] = []
        applied_changes = (
            exc.applied_changes
            if isinstance(exc, BulkUpdateError)
            else elasticsearch.changes if elasticsearch_written else ()
        )
        if applied_changes:
            try:
                client.update_sources(applied_changes, restore=True)
                verifier = getattr(client, "verify_restored_documents", None)
                if not callable(verifier):
                    raise RuntimeError(
                        "manual recovery required: Elasticsearch client lacks "
                        "full-document rollback verification"
                    )
                verifier(applied_changes)
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"Elasticsearch rollback incomplete: {rollback_exc}"
                )
        if markdown_written:
            try:
                _write_markdown_changes(
                    corpus,
                    locked_changes,
                    restore=True,
                    locks_held=True,
                    corpus_fd=corpus_fd,
                    expected_identities=markdown_identities,
                    offline_replace=offline_exfat,
                )
            except Exception as rollback_exc:
                rollback_errors.append(f"Markdown rollback failed: {rollback_exc}")
        try:
            _verify_directory_binding(backup_dir, backup_fd)
        except Exception as backup_exc:
            rollback_errors.append(f"Backup binding lost: {backup_exc}")
        if rollback_errors:
            raise RuntimeError(
                f"Migration failed ({exc}); recovery backup: {backup_dir}; "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def run_migration(
    corpus_root: Path,
    client: Any,
    *,
    index: str = DEFAULT_INDEX,
    apply: bool = False,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    offline_exfat: bool = False,
    source_renames: Mapping[str, str] | None = None,
) -> MigrationSummary:
    source_renames = _validated_source_renames(source_renames)
    _reject_symlink_components(Path(corpus_root))
    corpus, corpus_fd = _open_directory_no_follow(Path(corpus_root))
    try:
        if apply and offline_exfat:
            with corpus_write_lock(corpus, timeout=120):
                return _run_migration_retained(
                    corpus,
                    corpus_fd,
                    client,
                    index=index,
                    apply=apply,
                    backup_root=backup_root,
                    offline_exfat=offline_exfat,
                    source_renames=source_renames,
                )
        return _run_migration_retained(
            corpus,
            corpus_fd,
            client,
            index=index,
            apply=apply,
            backup_root=backup_root,
            offline_exfat=offline_exfat,
            source_renames=source_renames,
        )
    finally:
        os.close(corpus_fd)


def _run_migration_retained(
    corpus: Path,
    corpus_fd: int,
    client: Any,
    *,
    index: str,
    apply: bool,
    backup_root: Path,
    offline_exfat: bool,
    source_renames: Mapping[str, str] | None,
) -> MigrationSummary:
    markdown = scan_markdown(
        corpus, corpus_fd=corpus_fd, source_renames=source_renames,
    )
    elasticsearch = (
        client.scan_media(index)
        if source_renames is None
        else client.scan_media(index, source_renames=source_renames)
    )
    _validate_cross_store_sources(markdown, elasticsearch)
    counts = Counter(markdown.source_counts)
    counts.update(change.new_source for change in elasticsearch.changes)
    markdown_entries = sum(len(change.changes) for change in markdown.changes)
    markdown_files = len(markdown.changes)
    elasticsearch_documents = len(elasticsearch.changes)
    unresolved_markdown = len(markdown.unresolved_ids)
    unresolved_elasticsearch = len(elasticsearch.unresolved_ids)
    source_counts = dict(sorted(counts.items()))
    if not apply or (not markdown.changes and not elasticsearch.changes):
        return MigrationSummary(
            markdown_entries=markdown_entries,
            markdown_files=markdown_files,
            elasticsearch_documents=elasticsearch_documents,
            unresolved_markdown=unresolved_markdown,
            unresolved_elasticsearch=unresolved_elasticsearch,
            source_counts=source_counts,
            applied=False if not apply else True,
        )
    with _markdown_locks(
        corpus, markdown.changes, corpus_fd=corpus_fd,
    ) as (locked_changes, corpus_fd):
        _verify_directory_binding(corpus, corpus_fd)
        backup_result = _create_backup(
            corpus,
            markdown,
            elasticsearch,
            backup_root,
            corpus_fd=corpus_fd,
            retain_descriptor=True,
        )
        if not isinstance(backup_result, tuple):
            raise RuntimeError("Retained backup descriptor was not returned.")
        backup_dir, backup_fd = backup_result
        try:
            _apply_transaction(
                corpus,
                corpus_fd,
                locked_changes,
                markdown,
                elasticsearch,
                client,
                index=index,
                source_renames=source_renames,
                offline_exfat=offline_exfat,
                backup_dir=backup_dir,
                backup_fd=backup_fd,
            )
        finally:
            os.close(backup_fd)
    return MigrationSummary(
        markdown_entries=markdown_entries,
        markdown_files=markdown_files,
        elasticsearch_documents=elasticsearch_documents,
        unresolved_markdown=unresolved_markdown,
        unresolved_elasticsearch=unresolved_elasticsearch,
        source_counts=source_counts,
        applied=True,
        backup_dir=backup_dir,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply after backup; default is dry-run")
    parser.add_argument("--corpus", help="Override HFL corpus path")
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    parser.add_argument(
        "--rename",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help=(
            "Rename an exact source label while preserving entry IDs; may be "
            "repeated. Without --rename, the legacy media classifier is used."
        ),
    )
    parser.add_argument(
        "--offline-exfat",
        action="store_true",
        help=(
            "Use retained-inode writes on filesystems without hard links/atomic "
            "exchange; apply holds the corpus-wide writer lock"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _load_env_file()
    source_renames: dict[str, str] | None = None
    if args.rename:
        source_renames = {}
        for item in args.rename:
            old, separator, new = item.partition("=")
            old, new = old.strip(), new.strip()
            if not separator or not old or not new or old == new:
                raise SystemExit(f"Invalid --rename value: {item!r}; expected OLD=NEW")
            if old in source_renames and source_renames[old] != new:
                raise SystemExit(f"Conflicting --rename values for {old!r}")
            source_renames[old] = new
        if set(source_renames).intersection(source_renames.values()):
            raise SystemExit("Source rename chains/cycles are not supported")
    summary = run_migration(
        resolve_corpus_root(args.corpus), elasticsearch_client_from_env(),
        index=args.index, apply=args.apply, backup_root=Path(args.backup_root),
        offline_exfat=args.offline_exfat,
        source_renames=source_renames,
    )
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "applied": summary.applied,
        "markdown_entries": summary.markdown_entries,
        "markdown_files": summary.markdown_files,
        "elasticsearch_documents": summary.elasticsearch_documents,
        "unresolved_markdown": summary.unresolved_markdown,
        "unresolved_elasticsearch": summary.unresolved_elasticsearch,
        "source_counts": summary.source_counts,
        "backup_dir": str(summary.backup_dir) if summary.backup_dir else None,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
