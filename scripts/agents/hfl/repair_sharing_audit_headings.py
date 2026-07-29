#!/usr/bin/env python3
"""Dry-run-first repair for sharing-audit answers split by visible H2 headings."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urljoin

if TYPE_CHECKING:
    from workflows.hfl.dto import HflEntry

_DATE_TITLE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"
)
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_H2_LINE = re.compile(r"^## (.+?)\s*$")
_H3_LINE = re.compile(r"^### (.+?)\s*$")
_ENTRY_ID_LINE = re.compile(r"^Entry ID:\s*(\S+)\s*$")
_AUTHORIZED = {
    "hfl-c62394a3bc09eef72c9f74a3": (
        "2026-07-28.md",
        "c40af0a5f3c1bc84a1635ca7a05da86b5ed00bb18c1f66f79aa199c1a52535b3",
        "82e50f4d0451c0c603cfde52e232ed5a3786b9c2ebead9922fbea7724005d842",
    ),
    "hfl-060625883864ef41e41b212c": (
        "2026-07-29.md",
        "f8c67c8b45c62996b8e7f7b52edef033f7f96e72068ba871bc414372687b38d8",
        "8e8f833659c210742f46792117638c478dc160c328e60293e845af38cde2b968",
    ),
}


@dataclass(frozen=True)
class RepairReport:
    target_blocks: int
    detached_regions: int
    before_sha256: str
    after_sha256: str


@dataclass(frozen=True)
class StructuralLine:
    start: int
    end: int
    text: str


def _structural_lines(text: str) -> list[StructuralLine]:
    """Return lines outside backtick/tilde fences, preserving byte offsets."""
    lines: list[StructuralLine] = []
    fence_char = ""
    fence_length = 0
    offset = 0
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        if fence_char:
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.lstrip(" ") if indent <= 3 else line
            if re.fullmatch(
                rf"{re.escape(fence_char)}{{{fence_length},}}[ \t]*", stripped
            ):
                fence_char, fence_length = "", 0
            offset += len(raw)
            continue
        opener = _FENCE_OPEN.match(line)
        if opener and opener.group(1).startswith("`") and "`" in opener.group(2):
            opener = None
        if opener:
            marker = opener.group(1)
            fence_char, fence_length = marker[0], len(marker)
        else:
            lines.append(StructuralLine(offset, offset + len(raw), line))
        offset += len(raw)
    return lines


def _headings(text: str, pattern: re.Pattern[str]) -> list[tuple[StructuralLine, str]]:
    matches: list[tuple[StructuralLine, str]] = []
    for line in _structural_lines(text):
        match = pattern.fullmatch(line.text)
        if match:
            matches.append((line, match.group(1)))
    return matches


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dated_blocks(text: str) -> list[tuple[int, int, str]]:
    matches = [
        line
        for line, title in _headings(text or "", _H2_LINE)
        if _DATE_TITLE.fullmatch(title)
    ]
    return [
        (
            line.start,
            matches[index + 1].start if index + 1 < len(matches) else len(text),
            text[
                line.start:
                matches[index + 1].start if index + 1 < len(matches) else len(text)
            ],
        )
        for index, line in enumerate(matches)
    ]


def _block_entry_id(block: str) -> str:
    matches = [
        match.group(1)
        for line in _structural_lines(block)
        if (match := _ENTRY_ID_LINE.fullmatch(line.text))
    ]
    return matches[0] if len(matches) == 1 else ""


def repair_text(text: str, entry: HflEntry) -> tuple[str, RepairReport]:
    """Replace one exact damaged entry and remove only its detached H2 suffix."""
    if entry.source != "sharing-audit" or not entry.entry_id:
        raise RuntimeError("repair target must be a canonical sharing-audit entry")

    target_blocks = [
        (start, end, block)
        for start, end, block in _dated_blocks(text)
        if _block_entry_id(block) == entry.entry_id
    ]
    if len(target_blocks) != 1:
        raise RuntimeError("expected exactly one target entry block")

    all_h2 = _headings(text, _H2_LINE)
    noncanonical = [
        (line, title) for line, title in all_h2 if not _DATE_TITLE.fullmatch(title)
    ]
    expected_titles = list(
        dict.fromkeys(title for _, title in _headings(entry.what_happened, _H3_LINE))
    )
    expected_rank = {title: index for index, title in enumerate(expected_titles)}
    candidates = [item for item in noncanonical if item[1] in expected_rank]

    if len({title for _, title in candidates}) != len(candidates):
        raise RuntimeError("ambiguous detached heading region")
    unexpected = [item[1] for item in noncanonical if item not in candidates]
    if unexpected:
        raise RuntimeError(
            "unrelated noncanonical H2 headings prevent targeted repair: "
            + ", ".join(unexpected)
        )
    if candidates:
        ranks = [expected_rank[title] for _, title in candidates]
        if ranks != sorted(ranks):
            raise RuntimeError("detached headings are not in source order")

    without_detached = text
    detached_regions = 0
    if candidates:
        start = candidates[0][0].start
        next_dated = next(
            (
                line.start
                for line, title in all_h2
                if line.start > start and _DATE_TITLE.fullmatch(title)
            ),
            len(text),
        )
        detached = text[start:next_dated]
        if "Tags:" not in detached or "question-answered" not in detached:
            raise RuntimeError("detached region lacks sharing-audit trailing metadata")
        without_detached = text[:start] + text[next_dated:]
        detached_regions = 1

    target_blocks = [
        (start, end, block)
        for start, end, block in _dated_blocks(without_detached)
        if _block_entry_id(block) == entry.entry_id
    ]
    if len(target_blocks) != 1:
        raise RuntimeError("target entry changed while removing detached region")
    start, end, block = target_blocks[0]
    if "Source:          sharing-audit" not in block:
        raise RuntimeError("target block source changed")
    repaired = without_detached[:start] + entry.to_markdown() + without_detached[end:]
    return repaired, RepairReport(
        target_blocks=1,
        detached_regions=detached_regions,
        before_sha256=_sha256_text(text),
        after_sha256=_sha256_text(repaired),
    )


def _es_target(
    entry_id: str,
) -> tuple[HflEntry, dict[str, Any], tuple[int, int, int]]:
    from core.apps.es_logging.app.elasticsearch import _es_session
    from workflows.hfl.dto import HflEntry

    session, base = _es_session()
    index = quote(os.environ.get("HFL_ES_INDEX", "harqis-hfl-entries"), safe="-_.")
    response = session.get(
        urljoin(base, f"{index}/_doc/{quote(entry_id, safe='-_.')}"), timeout=20
    )
    if response.status_code != 200:
        raise RuntimeError(f"Elasticsearch lookup failed for {entry_id}: HTTP {response.status_code}")
    payload = response.json()
    if payload.get("found") is not True:
        raise RuntimeError(f"Elasticsearch document not found for {entry_id}")
    source = payload.get("_source")
    if not isinstance(source, dict):
        raise RuntimeError(f"Elasticsearch returned no source for {entry_id}")
    if payload.get("_id") != entry_id:
        raise RuntimeError(f"Elasticsearch document ID mismatch for {entry_id}")
    revision = tuple(payload.get(name) for name in ("_version", "_seq_no", "_primary_term"))
    if len(revision) != 3 or any(type(value) is not int for value in revision):
        raise RuntimeError(f"Elasticsearch revision mismatch for {entry_id}")
    required_strings = (
        "when", "entry_date", "source", "machine", "entry_id", "moment",
        "what_happened", "why_it_stayed", "possible_use",
    )
    if any(not isinstance(source.get(name), str) for name in required_strings):
        raise RuntimeError(f"Elasticsearch string-field shape mismatch for {entry_id}")
    source_entry_id = source["entry_id"]
    if source_entry_id != entry_id:
        raise RuntimeError(f"Elasticsearch identity mismatch for {entry_id}")
    if not isinstance(source.get("synthesized"), bool):
        raise RuntimeError(f"Elasticsearch synthesized shape mismatch for {entry_id}")
    for name in ("tags", "references"):
        value = source.get(name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise RuntimeError(f"Elasticsearch {name} shape mismatch for {entry_id}")
    when = datetime.fromisoformat(str(source["when"]))
    entry = HflEntry(
        when=when,
        source=str(source.get("source") or ""),
        machine=str(source.get("machine") or ""),
        entry_id=source_entry_id,
        synthesized=bool(source.get("synthesized")),
        moment=str(source.get("moment") or ""),
        what_happened=str(source.get("what_happened") or ""),
        why_it_stayed=str(source.get("why_it_stayed") or ""),
        possible_use=str(source.get("possible_use") or ""),
        tags=tuple(source.get("tags") or ()),
        references=tuple(source.get("references") or ()),
    )
    return entry, source, revision


def _assert_es_unchanged(
    entry_id: str,
    expected_entry: HflEntry,
    expected_source: dict[str, Any],
    expected_revision: tuple[int, int, int],
) -> None:
    current_entry, current_source, current_revision = _es_target(entry_id)
    if (
        current_source != expected_source
        or current_revision != expected_revision
        or current_entry.to_markdown() != expected_entry.to_markdown()
    ):
        raise RuntimeError(f"Elasticsearch source changed: {entry_id}")


def _fsync_directory_fd(directory_fd: int) -> None:
    os.fsync(directory_fd)


def _acquire_lock_at(
    resources: ExitStack, directory_fd: int, name: str, timeout: float = 30
) -> None:
    descriptor = os.open(
        name,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory_fd,
    )
    resources.callback(os.close, descriptor)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            resources.callback(fcntl.flock, descriptor, fcntl.LOCK_UN)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out acquiring lock: {name}")
            time.sleep(0.05)


def _open_directory_nofollow(path: Path) -> int:
    """Open every absolute path component without following symlinks."""
    absolute = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_file_at(directory_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"not a regular file: {name}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks), info
    finally:
        os.close(descriptor)


def _read_optional_file_at(
    directory_fd: int, name: str
) -> tuple[bytes, os.stat_result] | None:
    try:
        return _read_file_at(directory_fd, name)
    except FileNotFoundError:
        return None


def _sidecar_state(
    directory_fd: int, name: str
) -> tuple[bytes | None, tuple[int, int] | None, int | None]:
    result = _read_optional_file_at(directory_fd, f"._{name}")
    if result is None:
        return None, None, None
    content, info = result
    return content, (info.st_dev, info.st_ino), info.st_mode


def _sidecar_content_mode(
    state: tuple[bytes | None, tuple[int, int] | None, int | None]
) -> tuple[bytes | None, int | None]:
    return state[0], stat.S_IMODE(state[2]) if state[2] is not None else None


def _write_new_at(directory_fd: int, name: str, content: bytes, mode: int = 0o600) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode,
        dir_fd=directory_fd,
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_sidecar_at(
    directory_fd: int, name: str, content: bytes | None, mode: int | None
) -> None:
    sidecar_name = f"._{name}"
    try:
        os.unlink(sidecar_name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    if content is not None:
        _write_new_at(directory_fd, sidecar_name, content, stat.S_IMODE(mode or 0o600))
    _fsync_directory_fd(directory_fd)


def _atomic_write_at(
    directory_fd: int,
    name: str,
    content: bytes,
    mode: int,
    *,
    expected_identity: tuple[int, int],
    expected_sha256: str,
    expected_sidecar: tuple[bytes | None, tuple[int, int] | None, int | None],
    output_sidecar: tuple[bytes | None, tuple[int, int] | None, int | None],
    output_metadata: tuple[int, int, int, int] | None = None,
) -> tuple[int, int]:
    temporary_name = f".{name}.repair-{uuid.uuid4().hex}"
    descriptor = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        stat.S_IMODE(mode),
        dir_fd=directory_fd,
    )
    published_identity: tuple[int, int] | None = None
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        if output_metadata is not None:
            uid, gid, atime_ns, mtime_ns = output_metadata
            os.fchown(descriptor, uid, gid)
            os.fchmod(descriptor, stat.S_IMODE(mode))
            os.utime(descriptor, ns=(atime_ns, mtime_ns))
        os.fsync(descriptor)
        temporary_info = os.fstat(descriptor)
        published_identity = (temporary_info.st_dev, temporary_info.st_ino)
        current, current_info = _read_file_at(directory_fd, name)
        if (current_info.st_dev, current_info.st_ino) != expected_identity:
            raise RuntimeError(f"inode changed before publication: {name}")
        if hashlib.sha256(current).hexdigest() != expected_sha256:
            raise RuntimeError(f"bytes changed before publication: {name}")
        if _sidecar_state(directory_fd, name) != expected_sidecar:
            raise RuntimeError(f"metadata sidecar changed before publication: {name}")
        os.rename(
            temporary_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        _sync_sidecar_at(directory_fd, name, output_sidecar[0], output_sidecar[2])
        _fsync_directory_fd(directory_fd)
        return published_identity
    finally:
        os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _verify_metadata_at(
    directory_fd: int,
    name: str,
    mode: int,
    metadata: tuple[int, int, int, int],
    expected_identity: tuple[int, int],
) -> None:
    descriptor = os.open(
        name,
        os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=directory_fd,
    )
    try:
        uid, gid, atime_ns, mtime_ns = metadata
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"not a regular file: {name}")
        if (info.st_dev, info.st_ino) != expected_identity:
            raise RuntimeError(f"inode changed during metadata verification: {name}")
        if (
            info.st_uid != uid
            or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != stat.S_IMODE(mode)
            or info.st_mtime_ns != mtime_ns
        ):
            raise RuntimeError(f"primary metadata mismatch: {name}")
        os.utime(descriptor, ns=(atime_ns, mtime_ns))
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if (
            (info.st_dev, info.st_ino) != expected_identity
            or info.st_uid != uid
            or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != stat.S_IMODE(mode)
            or info.st_atime_ns != atime_ns
            or info.st_mtime_ns != mtime_ns
        ):
            raise RuntimeError(f"primary metadata restoration mismatch: {name}")
    finally:
        os.close(descriptor)


def _restore_at(
    directory_fd: int,
    name: str,
    original: bytes,
    mode: int,
    *,
    original_identity: tuple[int, int],
    original_sha256: str,
    published_sha256: str,
    original_sidecar: tuple[bytes | None, tuple[int, int] | None, int | None],
    published_sidecar: tuple[bytes | None, tuple[int, int] | None, int | None],
    original_metadata: tuple[int, int, int, int],
) -> None:
    current, current_info = _read_file_at(directory_fd, name)
    current_hash = hashlib.sha256(current).hexdigest()
    if current_hash == original_sha256:
        if (current_info.st_dev, current_info.st_ino) != original_identity:
            raise RuntimeError(f"original bytes moved to a different inode: {name}")
        _verify_metadata_at(
            directory_fd, name, mode, original_metadata, original_identity
        )
        return
    if current_hash != published_sha256:
        raise RuntimeError(f"refusing to overwrite non-migration bytes: {name}")
    restored_identity = _atomic_write_at(
        directory_fd,
        name,
        original,
        mode,
        expected_identity=(current_info.st_dev, current_info.st_ino),
        expected_sha256=published_sha256,
        expected_sidecar=published_sidecar,
        output_sidecar=original_sidecar,
        output_metadata=original_metadata,
    )
    restored, _ = _read_file_at(directory_fd, name)
    if hashlib.sha256(restored).hexdigest() != original_sha256:
        raise RuntimeError(f"rollback hash mismatch: {name}")
    if _sidecar_content_mode(_sidecar_state(directory_fd, name)) != _sidecar_content_mode(
        original_sidecar
    ):
        raise RuntimeError(f"rollback sidecar mismatch: {name}")
    _verify_metadata_at(
        directory_fd, name, mode, original_metadata, restored_identity
    )


def run(
    corpus: Path,
    entry_ids: list[str],
    *,
    apply: bool,
    writers_stopped: bool = False,
) -> dict[str, Any]:
    if apply and not writers_stopped:
        raise RuntimeError("apply requires confirmed writer quiescence")
    requested_corpus = corpus.expanduser().absolute()
    try:
        probe_fd = _open_directory_nofollow(requested_corpus)
    except OSError as exc:
        raise RuntimeError("corpus root cannot contain symlinks") from exc
    os.close(probe_fd)
    if len(entry_ids) != len(set(entry_ids)) or set(entry_ids) != set(_AUTHORIZED):
        raise RuntimeError("repair requires exactly the authorized entry IDs")

    targets: dict[str, list[HflEntry]] = {}
    es_sources: dict[str, dict[str, Any]] = {}
    es_revisions: dict[str, tuple[int, int, int]] = {}
    for entry_id in entry_ids:
        entry, source, revision = _es_target(entry_id)
        if entry.source != "sharing-audit":
            raise RuntimeError(f"unsupported repair target {entry_id}")
        expected_file, _, _ = _AUTHORIZED[entry_id]
        if f"{entry.when:%Y-%m-%d}.md" != expected_file:
            raise RuntimeError(f"authorized date mismatch for {entry_id}")
        if source["entry_date"] != expected_file.removesuffix(".md"):
            raise RuntimeError(f"Elasticsearch entry_date mismatch for {entry_id}")
        targets.setdefault(expected_file, []).append(entry)
        es_sources[entry_id] = source
        es_revisions[entry_id] = revision

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_name = f"sharing-heading-repair-{stamp}-{uuid.uuid4().hex[:8]}"
    backup_dir = requested_corpus / ".migrations" / backup_name
    prepared: list[dict[str, Any]] = []

    with ExitStack() as resources:
        corpus_fd = _open_directory_nofollow(requested_corpus)
        resources.callback(os.close, corpus_fd)
        corpus_info = os.fstat(corpus_fd)
        path_info = os.stat(requested_corpus, follow_symlinks=False)
        if (corpus_info.st_dev, corpus_info.st_ino) != (path_info.st_dev, path_info.st_ino):
            raise RuntimeError("corpus pathname binding changed")

        locks_fd = os.open(
            ".locks",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=corpus_fd,
        )
        resources.callback(os.close, locks_fd)
        locks_info = os.fstat(locks_fd)
        locks_identity = (locks_info.st_dev, locks_info.st_ino)
        for filename in sorted(targets):
            _acquire_lock_at(resources, locks_fd, f"{filename}.lock")
        current_locks = os.stat(".locks", dir_fd=corpus_fd, follow_symlinks=False)
        if (current_locks.st_dev, current_locks.st_ino) != locks_identity:
            raise RuntimeError("lock directory binding changed")

        for filename, entries in sorted(targets.items()):
            before_bytes, info = _read_file_at(corpus_fd, filename)
            sidecar = _sidecar_state(corpus_fd, filename)
            expected_hashes = {_AUTHORIZED[entry.entry_id][1] for entry in entries}
            before_hash = hashlib.sha256(before_bytes).hexdigest()
            if expected_hashes != {before_hash}:
                raise RuntimeError(f"preimage hash mismatch for {filename}")
            before = before_bytes.decode("utf-8")
            after = before
            reports: list[RepairReport] = []
            for entry in entries:
                after, report = repair_text(after, entry)
                reports.append(report)
            after_bytes = after.encode("utf-8")
            after_hash = hashlib.sha256(after_bytes).hexdigest()
            expected_after_hashes = {
                _AUTHORIZED[entry.entry_id][2] for entry in entries
            }
            if expected_after_hashes != {after_hash}:
                raise RuntimeError(f"postimage hash mismatch for {filename}")
            item = {
                "file": filename,
                "entry_ids": [entry.entry_id for entry in entries],
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "before_bytes": len(before_bytes),
                "after_bytes": len(after_bytes),
                "detached_regions": sum(report.detached_regions for report in reports),
                "changed": before_bytes != after_bytes,
                "mode": stat.S_IMODE(info.st_mode),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "atime_ns": info.st_atime_ns,
                "mtime_ns": info.st_mtime_ns,
            }
            if not item["changed"]:
                raise RuntimeError(f"repair unexpectedly made no change to {filename}")
            prepared.append({
                "filename": filename,
                "before_bytes": before_bytes,
                "after_bytes": after_bytes,
                "mode": info.st_mode,
                "metadata": (
                    info.st_uid,
                    info.st_gid,
                    info.st_atime_ns,
                    info.st_mtime_ns,
                ),
                "identity": (info.st_dev, info.st_ino),
                "sidecar": sidecar,
                "item": item,
            })

        results = [prepared_item["item"] for prepared_item in prepared]
        if apply:
            try:
                os.mkdir(".migrations", mode=0o700, dir_fd=corpus_fd)
            except FileExistsError:
                pass
            migrations_fd = os.open(
                ".migrations",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=corpus_fd,
            )
            resources.callback(os.close, migrations_fd)
            _fsync_directory_fd(corpus_fd)
            os.mkdir(backup_name, mode=0o700, dir_fd=migrations_fd)
            backup_fd = os.open(
                backup_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=migrations_fd,
            )
            resources.callback(os.close, backup_fd)

            for prepared_item in prepared:
                _write_new_at(
                    backup_fd,
                    prepared_item["filename"],
                    prepared_item["before_bytes"],
                )
                backup_bytes, _ = _read_file_at(backup_fd, prepared_item["filename"])
                if hashlib.sha256(backup_bytes).hexdigest() != prepared_item["item"]["before_sha256"]:
                    raise RuntimeError(
                        f"backup verification failed for {prepared_item['filename']}"
                    )
                if prepared_item["sidecar"][0] is not None:
                    sidecar_name = f"._{prepared_item['filename']}"
                    _sync_sidecar_at(
                        backup_fd,
                        prepared_item["filename"],
                        prepared_item["sidecar"][0],
                        prepared_item["sidecar"][2],
                    )
                    sidecar_backup, _ = _read_file_at(backup_fd, sidecar_name)
                    if sidecar_backup != prepared_item["sidecar"][0]:
                        raise RuntimeError(
                            f"sidecar backup verification failed for {prepared_item['filename']}"
                        )

            plan = json.dumps(
                {"created_at": stamp, "status": "prepared", "files": results},
                indent=2,
                sort_keys=True,
            ).encode("utf-8") + b"\n"
            _write_new_at(backup_fd, "plan.json", plan)
            _fsync_directory_fd(backup_fd)
            _fsync_directory_fd(migrations_fd)

            entries_by_id = {
                entry.entry_id: entry
                for entries in targets.values()
                for entry in entries
            }

            mutated: list[dict[str, Any]] = []
            try:
                for prepared_item in prepared:
                    for entry_id in prepared_item["item"]["entry_ids"]:
                        _assert_es_unchanged(
                            entry_id,
                            entries_by_id[entry_id],
                            es_sources[entry_id],
                            es_revisions[entry_id],
                        )
                    mutated.append(prepared_item)
                    published_identity = _atomic_write_at(
                        corpus_fd,
                        prepared_item["filename"],
                        prepared_item["after_bytes"],
                        prepared_item["mode"],
                        expected_identity=prepared_item["identity"],
                        expected_sha256=prepared_item["item"]["before_sha256"],
                        expected_sidecar=prepared_item["sidecar"],
                        output_sidecar=prepared_item["sidecar"],
                        output_metadata=prepared_item["metadata"],
                    )
                    actual, _ = _read_file_at(corpus_fd, prepared_item["filename"])
                    if hashlib.sha256(actual).hexdigest() != prepared_item["item"]["after_sha256"]:
                        raise RuntimeError(
                            f"post-write hash mismatch for {prepared_item['filename']}"
                        )
                    published_sidecar = _sidecar_state(
                        corpus_fd, prepared_item["filename"]
                    )
                    prepared_item["published_sidecar"] = published_sidecar
                    if _sidecar_content_mode(published_sidecar) != _sidecar_content_mode(
                        prepared_item["sidecar"]
                    ):
                        raise RuntimeError(
                            f"post-write sidecar mismatch for {prepared_item['filename']}"
                        )
                    _verify_metadata_at(
                        corpus_fd,
                        prepared_item["filename"],
                        prepared_item["mode"],
                        prepared_item["metadata"],
                        published_identity,
                    )
                manifest = json.dumps(
                    {"created_at": stamp, "status": "applied", "files": results},
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8") + b"\n"
                _write_new_at(backup_fd, "manifest.json", manifest)
                _fsync_directory_fd(backup_fd)
                _fsync_directory_fd(migrations_fd)
            except Exception as exc:
                rollback_errors: list[str] = []
                for prepared_item in reversed(mutated):
                    try:
                        _restore_at(
                            corpus_fd,
                            prepared_item["filename"],
                            prepared_item["before_bytes"],
                            prepared_item["mode"],
                            original_identity=prepared_item["identity"],
                            original_sha256=prepared_item["item"]["before_sha256"],
                            published_sha256=prepared_item["item"]["after_sha256"],
                            original_sidecar=prepared_item["sidecar"],
                            published_sidecar=prepared_item.get(
                                "published_sidecar",
                                _sidecar_state(corpus_fd, prepared_item["filename"]),
                            ),
                            original_metadata=prepared_item["metadata"],
                        )
                    except Exception as rollback_exc:  # noqa: BLE001
                        rollback_errors.append(
                            f"{prepared_item['filename']}: {rollback_exc}"
                        )
                detail = (
                    f"; rollback failures: {rollback_errors}"
                    if rollback_errors else ""
                )
                raise RuntimeError(
                    f"apply failed and rollback was attempted: {exc}{detail}"
                ) from exc

    return {
        "mode": "apply" if apply else "dry-run",
        "corpus": str(requested_corpus),
        "backup_dir": str(backup_dir) if apply else None,
        "files": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--entry-id", action="append", required=True, dest="entry_ids")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--writers-stopped",
        action="store_true",
        help="Confirm all HFL-capable writers are stopped (required with --apply)",
    )
    args = parser.parse_args()
    if args.apply and not args.writers_stopped:
        parser.error("--apply requires --writers-stopped")
    from scripts.launch import setup_env

    setup_env()
    print(json.dumps(run(
        args.corpus,
        args.entry_ids,
        apply=args.apply,
        writers_stopped=args.writers_stopped,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
