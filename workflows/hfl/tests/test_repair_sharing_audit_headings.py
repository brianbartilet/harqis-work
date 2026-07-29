from __future__ import annotations

import hashlib
import os
from contextlib import ExitStack
from datetime import datetime

import pytest
from filelock import FileLock

from scripts.agents.hfl import repair_sharing_audit_headings as migration
from scripts.agents.hfl.repair_sharing_audit_headings import repair_text
from workflows.hfl.dto import HflEntry


def _entry(entry_id: str, what_happened: str) -> HflEntry:
    return HflEntry(
        when=datetime(2026, 7, 29, 1, 56, 16, 372957),
        source="sharing-audit",
        machine="harqis-server",
        entry_id=entry_id,
        synthesized=False,
        moment="Corpus share question-answered",
        what_happened=what_happened,
        why_it_stayed="Audit trail for temporary corpus sharing.",
        possible_use="sharing-audit",
        tags=("sharing", "audit", "question-answered"),
    )


def test_repair_replaces_truncated_entry_and_removes_its_detached_fragments():
    entry = _entry(
        "hfl-target",
        "Event: question-answered\nAnswer: summary\n\n"
        "## Work & Career\nWork details\n\n"
        "## Personal Reflections\nReflection details",
    )
    damaged = (
        "~~~markdown`valid\n## 2026-07-29 10:00\nEntry ID:        hfl-target\n"
        "## Personal Reflections\n~~~\n\n"
        "````markdown\n## 2026-07-29 09:00\nEntry ID:        hfl-target\n"
        "## Work & Career\n````\n\n"
        "## 2026-07-29 02:00\nEntry ID:        hfl-newer\nMoment: newer\n\n"
        "## 2026-07-29 01:56:16.372957\n"
        "Source:          sharing-audit\n"
        "Entry ID:        hfl-target\n"
        "Moment:          Corpus share question-answered\n"
        "What happened:\nEvent: question-answered\nAnswer: summary\n\n"
        "## 2026-07-29 01:55\nEntry ID:        hfl-older\nMoment: older\n\n"
        "## Work & Career\nWork details\n\n"
        "## Personal Reflections\nReflection details\n"
        "Why it stayed:   Audit trail for temporary corpus sharing.\n"
        "Possible use:    sharing-audit\n"
        "Tags:            #sharing #audit #question-answered\n\n"
    )

    repaired, report = repair_text(damaged, entry)

    assert report.target_blocks == 1
    assert report.detached_regions == 1
    assert sum(
        migration._block_entry_id(block) == "hfl-target"
        for _, _, block in migration._dated_blocks(repaired)
    ) == 1
    assert not [
        title
        for _, title in migration._headings(repaired, migration._H2_LINE)
        if not migration._DATE_TITLE.fullmatch(title)
    ]
    assert "Work & Career" in [
        title for _, title in migration._headings(repaired, migration._H3_LINE)
    ]
    assert "\n### Personal Reflections\n" in repaired
    assert repaired.count("Entry ID:        hfl-newer") == 1
    assert repaired.count("Entry ID:        hfl-older") == 1
    assert repaired.startswith(
        "~~~markdown`valid\n## 2026-07-29 10:00\nEntry ID:        hfl-target\n"
        "## Personal Reflections\n~~~\n\n"
        "````markdown\n## 2026-07-29 09:00\nEntry ID:        hfl-target\n"
        "## Work & Career\n````\n\n"
    )


def test_repair_restores_entry_when_detached_fragments_are_already_missing():
    entry = _entry(
        "hfl-target",
        "Event: question-answered\nAnswer: summary\n\n"
        "## Work & Career\nWork details",
    )
    damaged = (
        "## 2026-07-29 01:56:16.372957\n"
        "Source:          sharing-audit\n"
        "Entry ID:        hfl-target\n"
        "Moment:          Corpus share question-answered\n"
        "What happened:\nEvent: question-answered\nAnswer: summary\n\n"
        "## 2026-07-29 01:55\nEntry ID:        hfl-older\nMoment: older\n\n"
    )

    repaired, report = repair_text(damaged, entry)

    assert report.target_blocks == 1
    assert report.detached_regions == 0
    assert "\n### Work & Career\n" in repaired
    assert repaired.count("Entry ID:        hfl-older") == 1


def test_repair_fails_closed_when_target_or_detached_heading_is_ambiguous():
    entry = _entry("hfl-target", "Answer: summary\n\n## Work & Career\nDetails")
    target = (
        "## 2026-07-29 01:56\nEntry ID:        hfl-target\nMoment: one\n\n"
    )
    with pytest.raises(RuntimeError, match="exactly one target"):
        repair_text(target + target, entry)

    one_target = target + (
        "## Work & Career\nDetails\nWhy it stayed: x\n"
        "## Work & Career\nDetails\nWhy it stayed: x\n"
    )
    with pytest.raises(RuntimeError, match="ambiguous detached"):
        repair_text(one_target, entry)


def test_apply_rolls_back_earlier_file_when_later_publication_fails(
    tmp_path, monkeypatch
):
    corpus = tmp_path / "hfl"
    (corpus / ".locks").mkdir(parents=True)
    first = _entry("hfl-first", "Answer:\n\n## Work & Career\nDetails")
    second = HflEntry(
        **{
            **first.__dict__,
            "when": datetime(2026, 7, 30, 1, 56, 16),
            "entry_id": "hfl-second",
        }
    )
    originals = {}
    for entry in (first, second):
        path = corpus / f"{entry.when:%Y-%m-%d}.md"
        text = (
            f"## {entry.when:%Y-%m-%d %H:%M:%S}\n"
            "Source:          sharing-audit\n"
            f"Entry ID:        {entry.entry_id}\n"
            "Moment:          Corpus share question-answered\n"
            "What happened:\nAnswer:\n\n"
            "## Work & Career\nDetails\n"
            "Why it stayed:   Audit trail for temporary corpus sharing.\n"
            "Tags:            #sharing #audit #question-answered\n\n"
        )
        path.write_text(text, encoding="utf-8")
        originals[path] = path.read_bytes()

    sidecar = corpus / f"._{first.when:%Y-%m-%d}.md"
    sidecar.write_bytes(b"CUSTOM-APPLEDOUBLE-METADATA")
    originals[sidecar] = sidecar.read_bytes()

    monkeypatch.setattr(
        migration,
        "_AUTHORIZED",
        {
            entry.entry_id: (
                f"{entry.when:%Y-%m-%d}.md",
                hashlib.sha256(originals[corpus / f"{entry.when:%Y-%m-%d}.md"]).hexdigest(),
                hashlib.sha256(
                    repair_text(
                        originals[corpus / f"{entry.when:%Y-%m-%d}.md"].decode(),
                        entry,
                    )[0].encode()
                ).hexdigest(),
            )
            for entry in (first, second)
        },
    )

    entries = {entry.entry_id: entry for entry in (first, second)}
    lookups = []

    def es_target(entry_id):
        lookups.append(entry_id)
        return (
            entries[entry_id],
            {"entry_date": f"{entries[entry_id].when:%Y-%m-%d}"},
            (1, 1, 1),
        )

    monkeypatch.setattr(migration, "_es_target", es_target)
    real_atomic_write = migration._atomic_write_at
    publications = 0

    def fail_after_second_publication(*args, **kwargs):
        nonlocal publications
        publications += 1
        result = real_atomic_write(*args, **kwargs)
        if publications == 2:
            raise OSError("injected post-publication failure")
        return result


    monkeypatch.setattr(migration, "_atomic_write_at", fail_after_second_publication)

    with pytest.raises(RuntimeError, match="rollback was attempted"):
        migration.run(
            corpus,
            ["hfl-first", "hfl-second"],
            apply=True,
            writers_stopped=True,
        )

    assert all(path.read_bytes() == original for path, original in originals.items())
    assert {entry_id: lookups.count(entry_id) for entry_id in entries} == {
        "hfl-first": 2,
        "hfl-second": 2,
    }
    backup_dirs = list((corpus / ".migrations").iterdir())
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "plan.json").is_file()
    assert not (backup_dirs[0] / "manifest.json").exists()


def test_restore_recovers_sidecar_after_metadata_publication_failure(tmp_path):
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        migration._write_new_at(directory_fd, "entry.md", b"before\n")
        migration._write_new_at(directory_fd, "._entry.md", b"ORIGINAL-METADATA")
        before, before_info = migration._read_file_at(directory_fd, "entry.md")
        original_sidecar = migration._sidecar_state(directory_fd, "entry.md")
        original_metadata = (
            before_info.st_uid,
            before_info.st_gid,
            before_info.st_atime_ns,
            before_info.st_mtime_ns,
        )
        migration._atomic_write_at(
            directory_fd,
            "entry.md",
            b"after\n",
            before_info.st_mode,
            expected_identity=(before_info.st_dev, before_info.st_ino),
            expected_sha256=hashlib.sha256(before).hexdigest(),
            expected_sidecar=original_sidecar,
            output_sidecar=original_sidecar,
            output_metadata=original_metadata,
        )
        published_info = migration._read_file_at(directory_fd, "entry.md")[1]
        assert (
            published_info.st_uid,
            published_info.st_gid,
            published_info.st_mtime_ns,
        ) == (before_info.st_uid, before_info.st_gid, before_info.st_mtime_ns)
        os.unlink("._entry.md", dir_fd=directory_fd)

        migration._restore_at(
            directory_fd,
            "entry.md",
            before,
            before_info.st_mode,
            original_identity=(before_info.st_dev, before_info.st_ino),
            original_sha256=hashlib.sha256(before).hexdigest(),
            published_sha256=hashlib.sha256(b"after\n").hexdigest(),
            original_sidecar=original_sidecar,
            published_sidecar=migration._sidecar_state(directory_fd, "entry.md"),
            original_metadata=original_metadata,
        )

        restored, restored_info = migration._read_file_at(directory_fd, "entry.md")
        assert restored == before
        assert (
            restored_info.st_uid,
            restored_info.st_gid,
            restored_info.st_mtime_ns,
        ) == (before_info.st_uid, before_info.st_gid, before_info.st_mtime_ns)
        assert migration._sidecar_content_mode(
            migration._sidecar_state(directory_fd, "entry.md")
        ) == migration._sidecar_content_mode(original_sidecar)
    finally:
        os.close(directory_fd)


def test_run_rejects_a_symlinked_corpus_root_before_es_lookup(tmp_path, monkeypatch):
    corpus = tmp_path / "real-corpus"
    corpus.mkdir()
    linked = tmp_path / "linked-corpus"
    linked.symlink_to(corpus, target_is_directory=True)
    monkeypatch.setattr(
        migration,
        "_AUTHORIZED",
        {"hfl-target": ("unused.md", "0" * 64, "0" * 64)},
    )
    monkeypatch.setattr(
        migration,
        "_es_target",
        lambda _entry_id: pytest.fail("ES lookup must not run for an unsafe root"),
    )

    with pytest.raises(RuntimeError, match="cannot contain symlinks"):
        migration.run(linked, ["hfl-target"], apply=False)


def test_descriptor_lock_interoperates_with_filelock_and_rejects_symlinks(tmp_path):
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        lock_path = tmp_path / "day.md.lock"
        with FileLock(lock_path):
            with ExitStack() as resources, pytest.raises(TimeoutError):
                migration._acquire_lock_at(
                    resources, directory_fd, lock_path.name, timeout=0.01
                )

        target = tmp_path / "target"
        target.write_text("do not lock", encoding="utf-8")
        (tmp_path / "unsafe.lock").symlink_to(target)
        with ExitStack() as resources, pytest.raises(OSError):
            migration._acquire_lock_at(resources, directory_fd, "unsafe.lock")
    finally:
        os.close(directory_fd)


def test_es_revalidation_rejects_revision_drift(monkeypatch):
    entry = _entry("hfl-target", "Answer: unchanged")
    source = {"entry_date": "2026-07-29"}
    monkeypatch.setattr(
        migration,
        "_es_target",
        lambda _entry_id: (entry, source, (1, 11, 3)),
    )

    with pytest.raises(RuntimeError, match="Elasticsearch source changed"):
        migration._assert_es_unchanged(
            entry.entry_id,
            entry,
            source,
            (1, 10, 3),
        )


def test_run_apply_requires_writer_quiescence(tmp_path):
    with pytest.raises(RuntimeError, match="writer quiescence"):
        migration.run(
            tmp_path,
            list(migration._AUTHORIZED),
            apply=True,
        )
