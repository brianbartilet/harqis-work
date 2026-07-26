#!/usr/bin/env python3
"""Demote historical agent-session H2 headings in HFL Markdown and ES.

The command is a dry-run unless ``--apply`` is supplied. Apply mode acquires
per-day corpus locks, creates private Markdown and Elasticsearch backups, then
updates both stores with rollback on failure. Canonical dated H2 entry headers,
fenced examples, non-agent-session entries, and non-daily corpus files are left
unchanged.
"""

from __future__ import annotations

import argparse
import base64
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INDEX = "harqis-hfl-entries"

_CANONICAL_HEADER_LINE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*$"
)
_CANONICAL_FIELD_LINE = re.compile(
    r"^(Moment|What happened|Why it stayed(?: with me)?|Possible use|Tags|"
    r"References|Source|Machine|Entry ID):[ \t]*(.*?)[ \t]*$",
    re.IGNORECASE,
)
_FIELD_RANK = {
    "moment": 0,
    "what happened": 1,
    "why it stayed": 2,
    "why it stayed with me": 2,
    "possible use": 3,
    "tags": 4,
    "references": 5,
    "source": 6,
    "machine": 7,
    "entry id": 8,
}
_VISIBLE_H2 = re.compile(r"^(\s*)##(\s+.+?)$")
_OPENING_FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")
_DAILY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


@dataclass(frozen=True)
class MarkdownChange:
    path: Path
    updated_text: str
    entry_ids: tuple[str, ...]
    headings_demoted: int
    relative_path: Path | None = None
    original_bytes: bytes | None = None
    mode: int = 0o600
    device: int = 0
    inode: int = 0


@dataclass(frozen=True)
class MarkdownWrite:
    change: MarkdownChange
    device: int
    inode: int
    data: bytes


@dataclass(frozen=True)
class ElasticsearchChange:
    index: str
    doc_id: str
    source: dict[str, Any]
    updated_what_happened: str
    entry_id: str
    headings_demoted: int
    seq_no: int = -1
    primary_term: int = -1


@dataclass(frozen=True)
class ElasticsearchWrite:
    change: ElasticsearchChange
    seq_no: int
    primary_term: int


@dataclass(frozen=True)
class MigrationSummary:
    markdown_files: int
    elasticsearch_documents: int
    markdown_headings_demoted: int
    elasticsearch_headings_demoted: int
    entry_ids: tuple[str, ...]
    applied: bool
    backup_dir: Path | None = None


class ElasticsearchBulkError(RuntimeError):
    def __init__(self, message: str, successful_writes: Iterable[ElasticsearchWrite] = ()):
        super().__init__(message)
        self.successful_writes = tuple(successful_writes)


def _line_body(line: str) -> str:
    return line.rstrip("\r\n")


def _opening_fence(line: str) -> tuple[str, int] | None:
    match = _OPENING_FENCE.fullmatch(_line_body(line))
    if not match:
        return None
    marker, info = match.groups()
    if marker[0] == "`" and "`" in info:
        return None
    return marker[0], len(marker)


def _is_closing_fence(line: str, character: str, opening_length: int) -> bool:
    body = _line_body(line)
    return bool(
        re.fullmatch(
            rf"[ ]{{0,3}}{re.escape(character)}{{{opening_length},}}[ \t]*",
            body,
        )
    )


def _canonical_field(line: str) -> tuple[str, str] | None:
    match = _CANONICAL_FIELD_LINE.fullmatch(_line_body(line))
    if not match:
        return None
    return match.group(1).casefold(), match.group(2).strip()


def _find_unclosed_fence_recovery(lines: list[str], opening_index: int) -> int | None:
    previous_rank = -1
    for line in lines[:opening_index]:
        field = _canonical_field(line)
        if field:
            previous_rank = max(previous_rank, _FIELD_RANK[field[0]])

    for candidate in range(opening_index + 1, len(lines)):
        field = _canonical_field(lines[candidate])
        if not field:
            continue
        rank = _FIELD_RANK[field[0]]
        if rank < 2 or rank <= previous_rank:
            continue
        suffix_fields = [
            parsed
            for line in lines[candidate:]
            if (parsed := _canonical_field(line)) is not None
        ]
        source_positions = [
            index
            for index, (name, value) in enumerate(suffix_fields)
            if name == "source" and value.casefold() == "agent-session"
        ]
        entry_positions = [
            index for index, (name, value) in enumerate(suffix_fields) if name == "entry id" and value
        ]
        if source_positions and entry_positions and source_positions[0] < entry_positions[-1]:
            return candidate
    return None


def _fenced_lines(
    text: str,
    *,
    recover_unclosed: bool,
    recover_unclosed_at_h2: bool = False,
) -> tuple[list[str], list[bool]]:
    lines = (text or "").splitlines(keepends=True)
    fenced = [False] * len(lines)
    index = 0
    while index < len(lines):
        opening = _opening_fence(lines[index])
        if not opening:
            index += 1
            continue
        character, length = opening
        closing = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if _is_closing_fence(lines[candidate], character, length)
            ),
            None,
        )
        if closing is not None:
            for candidate in range(index, closing + 1):
                fenced[candidate] = True
            index = closing + 1
            continue
        hard_boundary = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if _CANONICAL_HEADER_LINE.fullmatch(_line_body(lines[candidate]))
            ),
            len(lines),
        )
        # A malformed fence must never absorb a later canonical entry.
        recovery = (
            _find_unclosed_fence_recovery(lines[:hard_boundary], index)
            if recover_unclosed
            else None
        )
        h2_recovery = (
            next(
                (
                    candidate
                    for candidate in range(index + 1, hard_boundary)
                    if _VISIBLE_H2.fullmatch(_line_body(lines[candidate]))
                ),
                None,
            )
            if recover_unclosed_at_h2
            else None
        )
        stops = [hard_boundary]
        if recovery is not None:
            stops.append(recovery)
        if h2_recovery is not None:
            stops.append(h2_recovery)
        stop = min(stops)
        for candidate in range(index, stop):
            fenced[candidate] = True
        index = stop
    return lines, fenced


def migrate_what_happened(
    text: str,
    *,
    recover_at_fields: bool = False,
    recover_at_h2: bool = False,
) -> tuple[str, int]:
    lines, fenced = _fenced_lines(
        text,
        recover_unclosed=recover_at_fields,
        recover_unclosed_at_h2=recover_at_h2,
    )
    output: list[str] = []
    count = 0
    for index, line in enumerate(lines):
        if fenced[index]:
            output.append(line)
            continue
        ending = line[len(_line_body(line)) :]
        updated, demoted = _VISIBLE_H2.subn(r"\1###\2", _line_body(line))
        output.append(updated + ending)
        count += demoted
    return "".join(output), count


def _demote_nested_h2(block: str) -> tuple[str, int]:
    lines, fenced = _fenced_lines(block, recover_unclosed=True)
    output: list[str] = []
    count = 0
    for index, line in enumerate(lines):
        if index == 0 or fenced[index]:
            output.append(line)
            continue
        ending = line[len(_line_body(line)) :]
        updated, demoted = _VISIBLE_H2.subn(r"\1###\2", _line_body(line))
        output.append(updated + ending)
        count += demoted
    return "".join(output), count


def _canonical_fields(block: str) -> dict[str, str]:
    lines, fenced = _fenced_lines(block, recover_unclosed=True)
    visible_fields: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        if fenced[index]:
            continue
        parsed = _canonical_field(line)
        if parsed:
            visible_fields.append((index, parsed[0], parsed[1]))

    what_index = next(
        (index for index, name, _ in visible_fields if name == "what happened"),
        len(lines),
    )
    leading_sources = [item for item in visible_fields if item[1] == "source" and item[0] < what_index]
    source = leading_sources[-1] if leading_sources else next(
        (item for item in reversed(visible_fields) if item[1] == "source"),
        None,
    )
    if source is None:
        return {}
    entry_id = next(
        (
            value
            for index, name, value in visible_fields
            if name == "entry id"
            and index > source[0]
            and (source[0] >= what_index or index < what_index)
        ),
        "",
    )
    if not entry_id and source[0] >= what_index:
        entry_id = next(
            (
                value
                for index, name, value in reversed(visible_fields)
                if name == "entry id" and index > source[0]
            ),
            "",
        )
    return {"source": source[2], "entry id": entry_id}


def _safe_report_id(value: str, fallback: str = "unknown-entry") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", (value or "").strip()).strip("-")
    return cleaned[:160] or fallback


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
                "seq_no_primary_term": True,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"source.keyword": "agent-session"}},
                            {"exists": {"field": "what_happened"}},
                        ]
                    }
                },
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
                    if str(source.get("source") or "").strip().casefold() != "agent-session":
                        continue
                    what_happened = source.get("what_happened")
                    if not isinstance(what_happened, str):
                        continue
                    updated, demoted = migrate_what_happened(
                        what_happened,
                        recover_at_fields=True,
                        recover_at_h2=True,
                    )
                    if not demoted:
                        continue
                    doc_id = str(hit.get("_id") or "")
                    entry_id = _safe_report_id(
                        str(source.get("entry_id") or doc_id or "unknown-entry")
                    )
                    changes.append(
                        ElasticsearchChange(
                            index=str(hit.get("_index") or index),
                            doc_id=doc_id,
                            source=copy.deepcopy(source),
                            updated_what_happened=updated,
                            entry_id=entry_id,
                            headings_demoted=demoted,
                            seq_no=int(hit.get("_seq_no", -1)),
                            primary_term=int(hit.get("_primary_term", -1)),
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

    def revalidate(self, changes: list[ElasticsearchChange]) -> None:
        if not changes:
            return
        response = self._request(
            "POST",
            "/_mget",
            {"docs": [{"_index": change.index, "_id": change.doc_id} for change in changes]},
        )
        documents = response.get("docs")
        if not isinstance(documents, list) or len(documents) != len(changes):
            raise RuntimeError("Elasticsearch revalidation returned an incomplete response.")
        for change, document in zip(changes, documents, strict=True):
            if (
                not document.get("found")
                or int(document.get("_seq_no", -2)) != change.seq_no
                or int(document.get("_primary_term", -2)) != change.primary_term
                or document.get("_source") != change.source
            ):
                raise RuntimeError(
                    f"Elasticsearch document changed during migration preflight: {change.entry_id}"
                )

    def update_what_happened(
        self,
        changes: Iterable[ElasticsearchChange | ElasticsearchWrite],
        *,
        restore: bool = False,
    ) -> tuple[ElasticsearchWrite, ...]:
        items_to_write = list(changes)
        if not items_to_write:
            return ()
        lines: list[str] = []
        normalized: list[tuple[ElasticsearchChange, int, int]] = []
        for item in items_to_write:
            if restore:
                if not isinstance(item, ElasticsearchWrite):
                    raise ValueError("Elasticsearch restore requires confirmed write results.")
                change = item.change
                seq_no = item.seq_no
                primary_term = item.primary_term
                value = str(change.source.get("what_happened") or "")
            else:
                if not isinstance(item, ElasticsearchChange):
                    raise ValueError("Elasticsearch updates require scanned changes.")
                change = item
                seq_no = change.seq_no
                primary_term = change.primary_term
                value = change.updated_what_happened
            if seq_no < 0 or primary_term < 0:
                raise RuntimeError(
                    f"Elasticsearch concurrency token is missing for {change.entry_id}."
                )
            normalized.append((change, seq_no, primary_term))
            lines.append(
                json.dumps(
                    {
                        "update": {
                            "_index": change.index,
                            "_id": change.doc_id,
                            "if_seq_no": seq_no,
                            "if_primary_term": primary_term,
                        }
                    },
                    separators=(",", ":"),
                )
            )
            lines.append(
                json.dumps(
                    {"doc": {"what_happened": value}},
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
        response = self._request(
            "POST",
            "/_bulk?refresh=wait_for",
            raw_body=("\n".join(lines) + "\n").encode("utf-8"),
            content_type="application/x-ndjson",
        )
        results = response.get("items")
        if not isinstance(results, list):
            raise ElasticsearchBulkError(
                "Elasticsearch returned an incomplete per-item bulk response."
            )
        successful: list[ElasticsearchWrite] = []
        failures: list[str] = []
        for (change, _, _), result in zip(normalized, results):
            update = result.get("update") if isinstance(result, dict) else None
            if not isinstance(update, dict):
                failures.append(f"{change.entry_id}: malformed bulk response")
                continue
            try:
                status_code = int(update.get("status", 0))
                result_seq = int(update.get("_seq_no", -1))
                result_term = int(update.get("_primary_term", -1))
            except (TypeError, ValueError):
                failures.append(f"{change.entry_id}: malformed bulk response")
                continue
            if 200 <= status_code < 300 and not update.get("error"):
                if result_seq < 0 or result_term < 0:
                    failures.append(f"{change.entry_id}: successful response omitted concurrency tokens")
                else:
                    successful.append(ElasticsearchWrite(change, result_seq, result_term))
            else:
                failures.append(f"{change.entry_id}: HTTP {status_code or 'unknown'}")
        if len(results) != len(normalized):
            failures.append(
                f"incomplete response: expected {len(normalized)} items, received {len(results)}"
            )
        if failures or response.get("errors"):
            action = "restore" if restore else "update"
            raise ElasticsearchBulkError(
                f"Elasticsearch {action} failed for: {', '.join(failures) or 'unknown item'}.",
                successful,
            )
        return tuple(successful)


def migrate_markdown_text(text: str) -> tuple[str, tuple[str, ...], int]:
    lines, fenced = _fenced_lines(text or "", recover_unclosed=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)
    boundaries = [
        offsets[index]
        for index, line in enumerate(lines)
        if not fenced[index] and _CANONICAL_HEADER_LINE.fullmatch(_line_body(line))
    ]
    if not boundaries:
        return text, (), 0
    output = [text[: boundaries[0]]]
    entry_ids: list[str] = []
    total = 0
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else len(text)
        block = text[start:end]
        fields = _canonical_fields(block)
        if fields.get("source", "").casefold() == "agent-session":
            block, demoted = _demote_nested_h2(block)
            if demoted:
                entry_ids.append(fields.get("entry id") or f"legacy-entry-{index + 1}")
                total += demoted
        output.append(block)
    return "".join(output), tuple(entry_ids), total


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _open_root(corpus_root: Path) -> int:
    root = _lexical_absolute(corpus_root)
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError as exc:
        raise ValueError("The HFL corpus directory does not exist.") from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise ValueError("The HFL corpus directory must not be a symlink.")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("The HFL corpus directory does not exist.")
    return os.open(root, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)


def _relative_parts(relative: Path) -> tuple[str, ...]:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"Unsafe corpus-relative path: {relative}")
    return pure.parts


def _open_parent(root_fd: int, relative: Path) -> tuple[int, str]:
    parts = _relative_parts(relative)
    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=current)
            os.close(current)
            current = next_fd
        return current, parts[-1]
    except Exception:
        os.close(current)
        raise


def _open_or_create_directory(parent_fd: int, name: str, mode: int = 0o700) -> int:
    if not name or name in {".", ".."} or "/" in name:
        raise ValueError(f"Unsafe directory component: {name!r}")
    try:
        return os.open(name, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, mode, dir_fd=parent_fd)
        except FileExistsError:
            pass
        return os.open(name, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=parent_fd)


def _open_absolute_directory(path: Path, *, create: bool) -> int:
    absolute = _lexical_absolute(path)
    current = os.open("/", os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    try:
        for part in absolute.parts[1:]:
            next_fd = (
                _open_or_create_directory(current, part)
                if create
                else os.open(part, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=current)
            )
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _write_new_file(directory_fd: int, name: str, data: bytes, mode: int = 0o600) -> None:
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
        mode,
        dir_fd=directory_fd,
    )
    try:
        view = memoryview(data)
        written = 0
        while written < len(view):
            written += os.write(fd, view[written:])
        os.fsync(fd)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _read_relative(root_fd: int, relative: Path) -> tuple[bytes, os.stat_result]:
    parent_fd, name = _open_parent(root_fd, relative)
    try:
        fd = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise ValueError(f"Daily corpus path is not a regular file: {relative}")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks), details
    finally:
        os.close(fd)


def _write_relative(
    root_fd: int,
    relative: Path,
    data: bytes,
    *,
    expected_identity: tuple[int, int] | None = None,
    expected_bytes: bytes | None = None,
) -> os.stat_result:
    parent_fd, name = _open_parent(root_fd, relative)
    temporary = f".{name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    guard = f".{name}.guard-{os.getpid()}-{uuid.uuid4().hex}"
    temporary_created = False
    guard_created = False
    try:
        current_fd = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
        try:
            details = os.fstat(current_fd)
            if not stat.S_ISREG(details.st_mode):
                raise ValueError(f"Daily corpus path is not a regular file: {relative}")
        finally:
            os.close(current_fd)

        temporary_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            stat.S_IMODE(details.st_mode),
            dir_fd=parent_fd,
        )
        temporary_created = True
        try:
            view = memoryview(data)
            written = 0
            while written < len(view):
                written += os.write(temporary_fd, view[written:])
            os.fsync(temporary_fd)
            os.fchmod(temporary_fd, stat.S_IMODE(details.st_mode))
            temporary_details = os.fstat(temporary_fd)
        finally:
            os.close(temporary_fd)

        os.link(
            name,
            guard,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        guard_created = True
        verification_fd = os.open(guard, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
        try:
            destination = os.fstat(verification_fd)
            current_chunks: list[bytes] = []
            while chunk := os.read(verification_fd, 1024 * 1024):
                current_chunks.append(chunk)
            current_bytes = b"".join(current_chunks)
        finally:
            os.close(verification_fd)
        identity = (destination.st_dev, destination.st_ino)
        if expected_identity is not None and identity != expected_identity:
            raise RuntimeError(f"Corpus file identity changed before replacement: {relative}")
        if expected_bytes is not None and current_bytes != expected_bytes:
            raise RuntimeError(f"Corpus file contents changed before replacement: {relative}")
        destination = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (destination.st_dev, destination.st_ino) != identity:
            raise RuntimeError(f"Corpus file identity changed before replacement: {relative}")

        os.replace(
            temporary,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary_created = False
        installed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (installed.st_dev, installed.st_ino) != (
            temporary_details.st_dev,
            temporary_details.st_ino,
        ):
            raise RuntimeError(
                f"Corpus destination replaced concurrently after migration write: {relative}"
            )
        guard_fd = os.open(guard, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
        try:
            guarded_chunks: list[bytes] = []
            while chunk := os.read(guard_fd, 1024 * 1024):
                guarded_chunks.append(chunk)
            guarded_bytes = b"".join(guarded_chunks)
        finally:
            os.close(guard_fd)
        if guarded_bytes != current_bytes:
            os.replace(
                guard,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            guard_created = False
            os.fsync(parent_fd)
            raise RuntimeError(
                f"Corpus file changed during atomic replacement; concurrent version restored: {relative}"
            )
        os.unlink(guard, dir_fd=parent_fd)
        guard_created = False
        os.fsync(parent_fd)
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    finally:
        if temporary_created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        if guard_created:
            try:
                os.unlink(guard, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _daily_candidates(directory_fd: int, prefix: Path = Path()) -> list[Path]:
    candidates: list[Path] = []
    for name in sorted(os.listdir(directory_fd)):
        details = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        relative = prefix / name
        if stat.S_ISLNK(details.st_mode):
            raise ValueError(f"Corpus path component is a symlink: {relative}")
        if name.startswith("."):
            continue
        if stat.S_ISDIR(details.st_mode):
            child_fd = os.open(name, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=directory_fd)
            try:
                candidates.extend(_daily_candidates(child_fd, relative))
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(details.st_mode) and _DAILY_FILE.fullmatch(name):
            candidates.append(relative)
    return candidates


def _scan_markdown(corpus_root: Path, root_fd: int) -> list[MarkdownChange]:
    root = _lexical_absolute(corpus_root)
    candidates = _daily_candidates(root_fd)
    changes: list[MarkdownChange] = []
    for relative in sorted(candidates, key=lambda value: value.as_posix()):
        original, details = _read_relative(root_fd, relative)
        try:
            original_text = original.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Daily corpus file is not UTF-8: {relative}") from exc
        updated, entry_ids, demoted = migrate_markdown_text(original_text)
        if demoted:
            changes.append(
                MarkdownChange(
                    path=root / relative,
                    updated_text=updated,
                    entry_ids=entry_ids,
                    headings_demoted=demoted,
                    relative_path=relative,
                    original_bytes=original,
                    mode=stat.S_IMODE(details.st_mode),
                    device=details.st_dev,
                    inode=details.st_ino,
                )
            )
    return changes


def scan_markdown(corpus_root: Path) -> list[MarkdownChange]:
    root = _lexical_absolute(corpus_root)
    root_fd = _open_root(root)
    try:
        return _scan_markdown(root, root_fd)
    finally:
        os.close(root_fd)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _change_relative(change: MarkdownChange, corpus_root: Path) -> Path:
    if change.relative_path is not None:
        return change.relative_path
    try:
        return _lexical_absolute(change.path).relative_to(_lexical_absolute(corpus_root))
    except ValueError as exc:
        raise ValueError(f"Markdown change escaped the corpus: {change.path}") from exc


def _create_backup(
    corpus_root: Path,
    markdown_changes: list[MarkdownChange],
    es_changes: list[ElasticsearchChange],
    backup_root: Path,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-%f")
    backup_dir = _lexical_absolute(backup_root) / timestamp
    backup_root_fd = _open_absolute_directory(backup_root, create=True)
    try:
        os.mkdir(timestamp, 0o700, dir_fd=backup_root_fd)
        backup_fd = os.open(
            timestamp,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
            dir_fd=backup_root_fd,
        )
        try:
            os.mkdir("markdown", 0o700, dir_fd=backup_fd)
            markdown_fd = os.open(
                "markdown",
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                dir_fd=backup_fd,
            )
            markdown_manifest = []
            try:
                for change in markdown_changes:
                    relative = _change_relative(change, corpus_root)
                    before = change.original_bytes
                    if before is None:
                        raise RuntimeError(
                            f"Missing descriptor-bound backup bytes for {relative}."
                        )
                    parts = _relative_parts(relative)
                    destination_fd = os.dup(markdown_fd)
                    try:
                        for part in parts[:-1]:
                            next_fd = _open_or_create_directory(destination_fd, part)
                            os.close(destination_fd)
                            destination_fd = next_fd
                        _write_new_file(destination_fd, parts[-1], before)
                    finally:
                        os.close(destination_fd)
                    after = change.updated_text.encode("utf-8")
                    markdown_manifest.append(
                        {
                            "path": relative.as_posix(),
                            "before_bytes": len(before),
                            "after_bytes": len(after),
                            "before_sha256": _sha256(before),
                            "after_sha256": _sha256(after),
                            "headings_demoted": change.headings_demoted,
                            "entry_ids": list(change.entry_ids),
                        }
                    )
            finally:
                os.close(markdown_fd)

            es_payload = json.dumps(
                [
                    {
                        "_index": change.index,
                        "_id": change.doc_id,
                        "_seq_no": change.seq_no,
                        "_primary_term": change.primary_term,
                        "_source": change.source,
                    }
                    for change in es_changes
                ],
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
            _write_new_file(backup_fd, "elasticsearch.json", es_payload)
            manifest = {
                "markdown_files": len(markdown_changes),
                "elasticsearch_documents": len(es_changes),
                "markdown_headings_demoted": sum(
                    change.headings_demoted for change in markdown_changes
                ),
                "elasticsearch_headings_demoted": sum(
                    change.headings_demoted for change in es_changes
                ),
                "markdown": markdown_manifest,
                "elasticsearch": [
                    {
                        "_index": change.index,
                        "_id": change.doc_id,
                        "entry_id": change.entry_id,
                        "headings_demoted": change.headings_demoted,
                        "before_sha256": _sha256(
                            str(change.source.get("what_happened") or "").encode("utf-8")
                        ),
                        "after_sha256": _sha256(
                            change.updated_what_happened.encode("utf-8")
                        ),
                    }
                    for change in es_changes
                ],
            }
            _write_new_file(
                backup_fd,
                "manifest.json",
                (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            )
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)
        os.fsync(backup_root_fd)
    finally:
        os.close(backup_root_fd)
    return backup_dir


def _restore_markdown(
    root_fd: int,
    corpus_root: Path,
    markdown_writes: list[MarkdownWrite],
) -> None:
    failures: list[str] = []
    for write in markdown_writes:
        change = write.change
        relative = _change_relative(change, corpus_root)
        try:
            if change.original_bytes is None:
                raise RuntimeError("original bytes are unavailable")
            _write_relative(
                root_fd,
                relative,
                change.original_bytes,
                expected_identity=(write.device, write.inode),
                expected_bytes=write.data,
            )
        except Exception as exc:
            failures.append(f"{relative}: {exc}")
    if failures:
        raise RuntimeError("; ".join(failures))


def _lock_name(relative: Path) -> str:
    relative_text = relative.as_posix()
    digest = hashlib.sha256(relative_text.encode("utf-8")).hexdigest()[:20]
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "-", relative.name)
    return f"{safe_name}-{digest}.lock"


def _release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def run_migration(
    corpus_root: Path,
    es_client: Any,
    *,
    index: str = DEFAULT_INDEX,
    apply: bool = False,
    backup_root: Path,
) -> MigrationSummary:
    root = _lexical_absolute(corpus_root)
    root_fd = _open_root(root)
    try:
        markdown_changes = _scan_markdown(root, root_fd)
        es_changes = es_client.scan(index)
        entry_ids = tuple(
            dict.fromkeys(entry_id for change in markdown_changes for entry_id in change.entry_ids)
            | dict.fromkeys(change.entry_id for change in es_changes)
        )
        summary_values = {
            "markdown_files": len(markdown_changes),
            "elasticsearch_documents": len(es_changes),
            "markdown_headings_demoted": sum(change.headings_demoted for change in markdown_changes),
            "elasticsearch_headings_demoted": sum(change.headings_demoted for change in es_changes),
            "entry_ids": entry_ids,
        }
        if not apply or not (markdown_changes or es_changes):
            return MigrationSummary(**summary_values, applied=False)

        with ExitStack() as locks:
            lock_dir_fd = _open_or_create_directory(root_fd, ".locks")
            locks.callback(os.close, lock_dir_fd)
            lock_names = {
                _lock_name(_change_relative(change, root)) for change in markdown_changes
            }
            for lock_name in sorted(lock_names):
                lock_fd = os.open(
                    lock_name,
                    os.O_RDWR | os.O_CREAT | _NOFOLLOW,
                    0o600,
                    dir_fd=lock_dir_fd,
                )
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                except Exception:
                    os.close(lock_fd)
                    raise
                locks.callback(_release_lock, lock_fd)
            for change in markdown_changes:
                relative = _change_relative(change, root)
                current_bytes, _ = _read_relative(root_fd, relative)
                if current_bytes != change.original_bytes:
                    raise RuntimeError(f"Corpus file changed during migration preflight: {relative}")
                current = current_bytes.decode("utf-8")
                updated, entry_ids_now, demoted_now = migrate_markdown_text(current)
                if (
                    updated != change.updated_text
                    or entry_ids_now != change.entry_ids
                    or demoted_now != change.headings_demoted
                ):
                    raise RuntimeError(f"Corpus file changed during migration preflight: {relative}")

            es_client.revalidate(es_changes)
            backup_dir = _create_backup(root, markdown_changes, es_changes, backup_root)
            successful_es_writes: tuple[ElasticsearchWrite, ...] = ()
            successful_markdown_writes: list[MarkdownWrite] = []
            try:
                try:
                    successful_es_writes = tuple(es_client.update_what_happened(es_changes))
                except ElasticsearchBulkError as exc:
                    successful_es_writes = exc.successful_writes
                    raise
                for change in markdown_changes:
                    relative = _change_relative(change, root)
                    updated_bytes = change.updated_text.encode("utf-8")
                    result = _write_relative(
                        root_fd,
                        relative,
                        updated_bytes,
                        expected_identity=(change.device, change.inode),
                        expected_bytes=change.original_bytes,
                    )
                    successful_markdown_writes.append(
                        MarkdownWrite(change, result.st_dev, result.st_ino, updated_bytes)
                    )
            except Exception as migration_error:
                rollback_failures: list[str] = []
                try:
                    _restore_markdown(root_fd, root, successful_markdown_writes)
                except Exception as exc:
                    rollback_failures.append(f"Markdown restoration failed: {exc}")
                try:
                    es_client.update_what_happened(successful_es_writes, restore=True)
                except Exception as exc:
                    rollback_failures.append(f"Elasticsearch restoration failed: {exc}")
                if rollback_failures:
                    raise RuntimeError(
                        "MIGRATION FAILED AND ROLLBACK FAILURE(S) REQUIRE MANUAL RECOVERY: "
                        + " | ".join(rollback_failures)
                        + f" | Original failure: {migration_error}"
                    ) from migration_error
                raise
        return MigrationSummary(**summary_values, applied=True, backup_dir=backup_dir)
    finally:
        os.close(root_fd)


def _load_env_file() -> None:
    try:
        from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars

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
        return _lexical_absolute(Path(explicit))
    configured = os.environ.get("HFL_CORPUS_PATH", "").strip()
    if configured and "${" not in configured:
        return _lexical_absolute(Path(configured))
    try:
        from apps.apps_config import CONFIG_MANAGER

        hfl = CONFIG_MANAGER.get("HFL")
        configured = (hfl.get("corpus") or {}).get("path") if isinstance(hfl, dict) else None
        if configured and "${" not in configured:
            return _lexical_absolute(Path(configured))
    except Exception as exc:
        raise ValueError("The HFL corpus path could not be resolved.") from exc
    raise ValueError("The HFL corpus path is not configured.")


def _print_summary(summary: MigrationSummary) -> None:
    mode = "applied" if summary.applied else "dry-run"
    print(f"HFL noncanonical H2 migration ({mode})")
    print(f"  Markdown files: {summary.markdown_files}")
    print(f"  Markdown headings: {summary.markdown_headings_demoted}")
    print(f"  Elasticsearch documents: {summary.elasticsearch_documents}")
    print(f"  Elasticsearch headings: {summary.elasticsearch_headings_demoted}")
    print(f"  Distinct entry IDs: {len(summary.entry_ids)}")
    if summary.backup_dir:
        print(f"  Backup: {summary.backup_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
        help="Apply-mode backup root (default: <corpus>/.migrations/noncanonical-h2).",
    )
    args = parser.parse_args()
    _load_env_file()
    try:
        corpus_root = resolve_corpus_root(args.corpus)
        backup_root = args.backup_root or (corpus_root / ".migrations" / "noncanonical-h2")
        summary = run_migration(
            corpus_root,
            elasticsearch_client_from_env(),
            index=args.index,
            apply=args.apply,
            backup_root=backup_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
