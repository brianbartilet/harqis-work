import errno
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

from scripts.agents.hfl import migrate_media_sources as migration


def _entry(entry_id: str, reference: str, *, source: str = "media") -> str:
    return (
        "## 2026-07-26 19:59\n"
        f"Source:          {source}\n"
        f"Entry ID:        {entry_id}\n"
        f"Moment:          {entry_id}\n"
        "Tags:            #test\n"
        "References:\n"
        f"                 - {reference}\n\n"
    )


def test_migrate_markdown_reclassifies_only_conclusive_media_and_preserves_ids():
    desktop_ref = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    android_ref = (
        "/Volumes/harqis-data/dumps/"
        "nothing-phone-daily-dumps-2026-07-26/DCIM/Camera/photo.jpg"
    )
    unknown_ref = "/Volumes/harqis-data/imports/photo.jpg"
    original = (
        _entry("hfl-desktop", desktop_ref)
        + _entry("hfl-android", android_ref)
        + _entry("hfl-unknown", unknown_ref)
        + _entry("hfl-capture", desktop_ref, source="capture")
    )

    updated, changes, unresolved = migration.migrate_markdown_text(original)

    assert [change.entry_id for change in changes] == ["hfl-desktop", "hfl-android"]
    assert [change.new_source for change in changes] == ["desktop", "android-capture"]
    assert unresolved == ("hfl-unknown",)
    assert "Entry ID:        hfl-desktop" in updated
    assert "Entry ID:        hfl-android" in updated
    assert updated.count("Source:          desktop") == 1
    assert updated.count("Source:          android-capture") == 1
    assert updated.count("Source:          media") == 1
    assert updated.count("Source:          capture") == 1


def test_migrate_markdown_exact_source_renames_preserve_ids_links_and_text():
    echomtg = _entry(
        "hfl-echomtg", "https://www.echomtg.com/inventory/",
        source="echomtg_inventory",
    )
    android_reference = "/Volumes/harqis-data/dumps/android/screenshot.png"
    android = _entry(
        "hfl-android", android_reference, source="android_capture",
    )
    unrelated = _entry("hfl-git", "https://example.test/commit", source="git")
    original = echomtg + android + unrelated

    updated, changes, unresolved = migration.migrate_markdown_text(
        original,
        {
            "echomtg_inventory": "echomtg-inventory",
            "android_capture": "android-capture",
        },
    )

    assert [(change.entry_id, change.old_source, change.new_source) for change in changes] == [
        ("hfl-echomtg", "echomtg_inventory", "echomtg-inventory"),
        ("hfl-android", "android_capture", "android-capture"),
    ]
    assert unresolved == ()
    assert "Source:          echomtg-inventory" in updated
    assert "Source:          android-capture" in updated
    assert "Source:          git" in updated
    assert updated.replace("echomtg-inventory", "echomtg_inventory").replace(
        "android-capture", "android_capture",
    ) == original


def test_exact_source_scan_rejects_unrelated_duplicate_ids(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "2026-08-17.md").write_text(
        _entry("hfl-duplicate", "https://example.test/one", source="git"),
        encoding="utf-8",
    )
    (corpus / "2026-08-23.md").write_text(
        _entry("hfl-duplicate", "https://example.test/two", source="git"),
        encoding="utf-8",
    )
    (corpus / "2026-08-29.md").write_text(
        _entry("hfl-target", "https://www.echomtg.com/inventory/", source="echomtg_inventory"),
        encoding="utf-8",
    )

    try:
        migration.scan_markdown(
            corpus,
            source_renames={"echomtg_inventory": "echomtg-inventory"},
        )
    except RuntimeError as exc:
        assert "Duplicate HFL entry ID hfl-duplicate" in str(exc)
    else:
        raise AssertionError("all duplicate entry IDs must fail closed")


def test_exact_source_scan_rejects_duplicate_affected_ids(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for day in ("2026-08-28", "2026-08-29"):
        (corpus / f"{day}.md").write_text(
            _entry(
                "hfl-target",
                "https://www.echomtg.com/inventory/",
                source="echomtg_inventory",
            ),
            encoding="utf-8",
        )

    try:
        migration.scan_markdown(
            corpus,
            source_renames={"echomtg_inventory": "echomtg-inventory"},
        )
    except RuntimeError as exc:
        assert "Duplicate HFL entry ID hfl-target" in str(exc)
    else:
        raise AssertionError("duplicates among affected entries must fail closed")


def test_classification_rejects_forged_or_noncanonical_dump_references():
    forged = (
        "https://example.invalid/nothing-phone-daily-dumps-2026-07-26/"
        "DCIM/Camera/photo.jpg"
    )
    unrelated = (
        "/tmp/windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )

    assert migration.classify_references((forged,)) is None
    assert migration.classify_references((unrelated,)) is None
    assert migration.classify_references((
        "/Volumes/harqis-data/dumps/../dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg",
    )) is None


def test_migration_rejects_media_entry_without_canonical_id():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    block = _entry("hfl-missing", reference).replace(
        "Entry ID:        hfl-missing\n",
        "",
    )

    try:
        migration.migrate_markdown_text(block)
    except RuntimeError as exc:
        assert "canonical metadata Entry ID" in str(exc)
    else:
        raise AssertionError("classifiable entries without IDs must fail closed")


def test_migration_rejects_narrative_source_field():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    block = _entry("hfl-narrative", reference, source="capture").replace(
        "References:\n",
        "What happened:\nSource: media\nReferences:\n",
    )

    try:
        migration.migrate_markdown_text(block)
    except RuntimeError as exc:
        assert "exactly one canonical Source" in str(exc)
    else:
        raise AssertionError("narrative source lines must not be migrated")


def test_migration_rejects_narrative_or_duplicate_entry_id():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    canonical = _entry("hfl-canonical", reference)
    narrative_only = canonical.replace(
        "Entry ID:        hfl-canonical\n",
        "",
    ) + "What happened:\nEntry ID:        hfl-narrative\n"
    duplicate = canonical + "What happened:\nEntry ID:        hfl-duplicate\n"

    for malformed in (narrative_only, duplicate):
        try:
            migration.migrate_markdown_text(malformed)
        except RuntimeError as exc:
            assert "canonical metadata Entry ID" in str(exc)
        else:
            raise AssertionError("noncanonical Entry ID fields must fail closed")


def test_migrate_markdown_ignores_fenced_h2_entry_examples():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    fenced = "```markdown\n" + _entry("hfl-example", reference) + "```\n"

    updated, changes, unresolved = migration.migrate_markdown_text(fenced)

    assert updated == fenced
    assert changes == ()
    assert unresolved == ()


def test_scan_markdown_skips_hidden_files_and_reports_source_counts(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    desktop_ref = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    (corpus / "2026-07-26.md").write_text(
        _entry("hfl-desktop", desktop_ref), encoding="utf-8"
    )
    (corpus / "._2026-07-26.md").write_bytes(b"\x00\x05\x16\x07")

    scan = migration.scan_markdown(corpus)

    assert len(scan.changes) == 1
    assert scan.source_counts == {"desktop": 1}
    assert scan.unresolved_ids == ()


def test_scan_markdown_rejects_visible_symlinks(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (corpus / "2026-07-26.md").symlink_to(outside)

    try:
        migration.scan_markdown(corpus)
    except RuntimeError as exc:
        assert "symlink" in str(exc).casefold()
    else:
        raise AssertionError("visible corpus symlinks must fail closed")


def test_scan_markdown_rejects_symlinked_root_or_ancestor(tmp_path):
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(real_root, target_is_directory=True)
    ancestor_target = tmp_path / "ancestor-target"
    (ancestor_target / "corpus").mkdir(parents=True)
    ancestor_link = tmp_path / "ancestor-link"
    ancestor_link.symlink_to(ancestor_target, target_is_directory=True)

    for path in (root_link, ancestor_link / "corpus"):
        try:
            migration.scan_markdown(path)
        except RuntimeError as exc:
            assert "symlinked corpus path" in str(exc)
        else:
            raise AssertionError("symlinked corpus roots/ancestors must fail closed")


def test_markdown_write_rejects_symlink_swap_after_scan(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    day.write_text(_entry("hfl-swap", reference), encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    day.unlink()
    day.symlink_to(outside)

    try:
        migration._write_markdown_changes(corpus, scan.changes)
    except RuntimeError as exc:
        assert "symlink" in str(exc).casefold()
    else:
        raise AssertionError("post-scan symlink swaps must fail closed")

    assert outside.read_text(encoding="utf-8") == "outside"


def test_scan_and_write_support_nested_archive_files(tmp_path):
    corpus = tmp_path / "corpus"
    nested = corpus / "nested"
    nested.mkdir(parents=True)
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = nested / "2026-07-26.md"
    day.write_text(
        _entry("hfl-nested", reference),
        encoding="utf-8",
    )

    scan = migration.scan_markdown(corpus)

    assert len(scan.changes) == 1
    migration._write_markdown_changes(corpus, scan.changes)
    updated = day.read_text(encoding="utf-8")
    assert "Source:          desktop" in updated
    assert "Entry ID:        hfl-nested" in updated


def test_backup_preserves_nested_archive_layout(tmp_path):
    corpus = tmp_path / "corpus"
    nested = corpus / "2026" / "Jul"
    nested.mkdir(parents=True)
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = nested / "2026-07-26.md"
    original = _entry("hfl-nested-backup", reference)
    day.write_text(original, encoding="utf-8")
    sidecar = day.with_name(f"._{day.name}")
    sidecar_payload = b"opaque-appledouble"
    sidecar.write_bytes(sidecar_payload)
    scan = migration.scan_markdown(corpus)
    _root, corpus_fd = migration._open_directory_no_follow(corpus)
    try:
        backup = migration._create_backup(
            corpus,
            scan,
            migration.ElasticsearchScan((), ()),
            tmp_path / "backups",
            corpus_fd=corpus_fd,
        )
    finally:
        os.close(corpus_fd)

    assert isinstance(backup, Path)
    copied = backup / "markdown" / "2026" / "Jul" / day.name
    assert copied.read_text(encoding="utf-8") == original
    copied_sidecar = backup / "appledouble" / "2026" / "Jul" / sidecar.name
    assert copied_sidecar.read_bytes() == sidecar_payload
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["markdown_metadata"]["2026/Jul/2026-07-26.md"]
    original_stat = day.stat()
    assert metadata["uid"] == original_stat.st_uid
    assert metadata["gid"] == original_stat.st_gid
    assert metadata["mode"] == stat.S_IMODE(original_stat.st_mode)
    assert metadata["mtime_ns"] == original_stat.st_mtime_ns
    assert "atime_ns" in metadata
    assert "birthtime_ns" in metadata
    assert "flags" in metadata
    assert "acl" in metadata
    assert isinstance(metadata["xattrs_base64"], dict)
    sidecar_metadata = manifest["appledouble_metadata"]["2026/Jul/2026-07-26.md"]
    assert sidecar_metadata["opaque_appledouble"] is True
    assert sidecar_metadata["acl"] is None
    assert sidecar_metadata["xattrs_base64"] == {}
    sidecar_stat = sidecar.stat()
    assert sidecar_metadata["atime_ns"] == sidecar_stat.st_atime_ns
    assert sidecar_metadata["mtime_ns"] == sidecar_stat.st_mtime_ns


def test_markdown_write_rejects_corpus_root_symlink_swap(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-root-swap", reference)
    day.write_text(original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    moved = tmp_path / "moved-corpus"
    outside = tmp_path / "outside"
    outside.mkdir()

    with migration._markdown_locks(corpus, scan.changes) as (changes, corpus_fd):
        corpus.rename(moved)
        corpus.symlink_to(outside, target_is_directory=True)
        try:
            migration._write_markdown_changes(
                corpus,
                changes,
                locks_held=True,
                corpus_fd=corpus_fd,
            )
        except RuntimeError as exc:
            assert "corpus root changed" in str(exc)
        else:
            raise AssertionError("corpus-root swaps must fail closed")
        finally:
            corpus.unlink()
            moved.rename(corpus)

    assert day.read_text(encoding="utf-8") == original
    assert not tuple(outside.iterdir())


def test_scan_markdown_rejects_duplicate_entry_ids(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    duplicate = _entry("hfl-duplicate", reference)
    (corpus / "2026-07-25.md").write_text(duplicate, encoding="utf-8")
    (corpus / "2026-07-26.md").write_text(duplicate, encoding="utf-8")

    try:
        migration.scan_markdown(corpus)
    except RuntimeError as exc:
        assert "Duplicate HFL entry ID" in str(exc)
    else:
        raise AssertionError("duplicate entry IDs must fail closed")


def test_es_metadata_restores_precision_and_synthesis_for_shared_entries():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    original = _entry("hfl-desktop", reference)
    updated, _changes, _unresolved = migration.migrate_markdown_text(original)

    enriched = migration.enrich_markdown_metadata(updated, {
        "hfl-desktop": {
            "when": "2026-07-26T19:59:33.870000",
            "synthesized": True,
        },
    })

    assert enriched.startswith("## 2026-07-26 19:59:33.870\n")
    assert "Synthesized:     true" in enriched
    assert "Entry ID:        hfl-desktop" in enriched
    assert "Source:          desktop" in enriched


def test_es_metadata_never_overwrites_explicit_or_conflicting_canonical_values():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    explicit = _entry("hfl-explicit", reference).replace(
        "## 2026-07-26 19:59\n",
        "## 2026-07-26 19:59:12.345\n",
    ).replace(
        "Entry ID:        hfl-explicit\n",
        "Entry ID:        hfl-explicit\nSynthesized:     false\n",
    )
    updated, _changes, _unresolved = migration.migrate_markdown_text(explicit)

    enriched = migration.enrich_markdown_metadata(updated, {
        "hfl-explicit": {
            "when": "2026-07-27T20:00:33.870000",
            "synthesized": True,
        },
    })

    assert enriched.startswith("## 2026-07-26 19:59:12.345\n")
    assert "Synthesized:     false" in enriched
    assert "Synthesized:     true" not in enriched


def test_es_metadata_ignores_malformed_or_different_minute_timestamp():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    original = _entry("hfl-legacy", reference)
    updated, _changes, _unresolved = migration.migrate_markdown_text(original)

    malformed = migration.enrich_markdown_metadata(updated, {
        "hfl-legacy": {"when": "not-a-date"},
    })
    stale = migration.enrich_markdown_metadata(updated, {
        "hfl-legacy": {"when": "2026-07-26T20:00:33.870000"},
    })

    assert malformed.startswith("## 2026-07-26 19:59\n")
    assert stale.startswith("## 2026-07-26 19:59\n")


def test_es_metadata_enrichment_preserves_crlf_style():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    original = _entry("hfl-crlf", reference).replace("\n", "\r\n")
    updated, _changes, _unresolved = migration.migrate_markdown_text(original)

    enriched = migration.enrich_markdown_metadata(updated, {
        "hfl-crlf": {
            "when": "2026-07-26T19:59:33.870000",
            "synthesized": True,
        },
    })

    assert "\n" not in enriched.replace("\r\n", "")
    assert "Synthesized:     true\r\n" in enriched


def test_run_migration_is_dry_run_by_default_and_apply_is_idempotent(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    desktop_ref = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-desktop", desktop_ref)
    day.write_text(original, encoding="utf-8")

    class FakeClient:
        def __init__(self):
            self.source = "media"
            self.calls = []

        def scan_media(self, _index):
            if self.source != "media":
                return migration.ElasticsearchScan(
                    (), (), {"hfl-desktop": "desktop"},
                )
            return migration.ElasticsearchScan((migration.ElasticsearchChange(
                index="hfl", doc_id="hfl-desktop", entry_id="hfl-desktop",
                old_source="media", new_source="desktop",
                document={"entry_id": "hfl-desktop", "source": "media",
                          "references": [desktop_ref]},
            ),), ())

        def update_sources(self, changes, *, restore=False):
            self.calls.append((tuple(changes), restore))
            self.source = "media" if restore else "desktop"

        def verify_updated_documents(self, changes):
            assert self.source == "desktop"
            assert tuple(changes)

    client = FakeClient()
    dry = migration.run_migration(
        corpus, client, index="hfl", apply=False,
        backup_root=tmp_path / "backups",
    )
    assert dry.applied is False
    assert day.read_text(encoding="utf-8") == original
    assert client.calls == []

    applied = migration.run_migration(
        corpus, client, index="hfl", apply=True,
        backup_root=tmp_path / "backups",
    )
    assert applied.applied is True
    assert applied.markdown_entries == 1
    assert applied.elasticsearch_documents == 1
    assert applied.backup_dir is not None
    assert (applied.backup_dir / "manifest.json").is_file()
    manifest = json.loads((applied.backup_dir / "manifest.json").read_text())
    markdown_backup = applied.backup_dir / "markdown" / day.name
    assert stat.S_IMODE(applied.backup_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(markdown_backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(
        (applied.backup_dir / "elasticsearch.ndjson").stat().st_mode
    ) == 0o600
    assert manifest["markdown_sha256"][day.name] == hashlib.sha256(
        markdown_backup.read_bytes()
    ).hexdigest()
    assert manifest["elasticsearch_ndjson_sha256"] == hashlib.sha256(
        (applied.backup_dir / "elasticsearch.ndjson").read_bytes()
    ).hexdigest()
    assert "Source:          desktop" in day.read_text(encoding="utf-8")

    replay = migration.run_migration(
        corpus, client, index="hfl", apply=True,
        backup_root=tmp_path / "backups",
    )
    assert replay.markdown_entries == 0
    assert replay.elasticsearch_documents == 0
    assert len(client.calls) == 1


def test_apply_restores_markdown_when_elasticsearch_update_fails(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-desktop", reference)
    day.write_text(original, encoding="utf-8")

    class FailingClient:
        def scan_media(self, _index):
            return migration.ElasticsearchScan((migration.ElasticsearchChange(
                index="hfl", doc_id="hfl-desktop", entry_id="hfl-desktop",
                old_source="media", new_source="desktop",
                document={"entry_id": "hfl-desktop", "source": "media",
                          "references": [reference]},
            ),), ())

        def update_sources(self, _changes, *, restore=False):
            if not restore:
                raise RuntimeError("simulated bulk failure")

    try:
        migration.run_migration(
            corpus, FailingClient(), index="hfl", apply=True,
            backup_root=tmp_path / "backups",
        )
    except RuntimeError as exc:
        assert "simulated bulk failure" in str(exc)
        assert any("Recovery backup:" in note for note in exc.__notes__)
    else:
        raise AssertionError("bulk failure must abort the migration")

    assert day.read_text(encoding="utf-8") == original


def test_apply_and_rollback_preserve_crlf_bytes(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-crlf", reference).replace("\n", "\r\n").encode()
    day.write_bytes(original)

    class FailingClient:
        def scan_media(self, _index):
            return migration.ElasticsearchScan((migration.ElasticsearchChange(
                index="hfl", doc_id="hfl-crlf", entry_id="hfl-crlf",
                old_source="media", new_source="desktop",
                document={"entry_id": "hfl-crlf", "source": "media",
                          "references": [reference]},
            ),), ())

        def update_sources(self, _changes, *, restore=False):
            if not restore:
                raise RuntimeError("simulated bulk failure")

    try:
        migration.run_migration(
            corpus, FailingClient(), index="hfl", apply=True,
            backup_root=tmp_path / "backups",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("bulk failure must abort the migration")

    assert day.read_bytes() == original


def test_markdown_preflight_prevents_partial_multi_file_rewrite(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    first = corpus / "2026-07-25.md"
    second = corpus / "2026-07-26.md"
    first_original = _entry("hfl-first", reference)
    second_original = _entry("hfl-second", reference)
    first.write_text(first_original, encoding="utf-8")
    second.write_text(second_original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    second.write_text(second_original + "concurrent change\n", encoding="utf-8")

    try:
        migration._write_markdown_changes(corpus, scan.changes)
    except RuntimeError as exc:
        assert "Concurrent HFL corpus change" in str(exc)
    else:
        raise AssertionError("concurrent corpus mutation must abort the rewrite")

    assert first.read_text(encoding="utf-8") == first_original
    assert second.read_text(encoding="utf-8") == second_original + "concurrent change\n"


def test_markdown_revalidates_each_file_immediately_before_replace(
    tmp_path, monkeypatch,
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    first = corpus / "2026-07-25.md"
    second = corpus / "2026-07-26.md"
    first_original = _entry("hfl-first", reference)
    second_original = _entry("hfl-second", reference)
    first.write_text(first_original, encoding="utf-8")
    second.write_text(second_original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    swap_names = migration._swap_names
    writes = 0

    def race(dir_fd, first_name, second_name):
        nonlocal writes
        writes += 1
        if writes == 1:
            second.write_text(
                second_original + "late concurrent change\n",
                encoding="utf-8",
            )
        return swap_names(dir_fd, first_name, second_name)

    monkeypatch.setattr(migration, "_swap_names", race)

    try:
        migration._write_markdown_changes(corpus, scan.changes)
    except RuntimeError as exc:
        assert "Concurrent HFL corpus change" in str(exc)
    else:
        raise AssertionError("late corpus mutation must abort the rewrite")

    assert first.read_text(encoding="utf-8") == first_original
    assert second.read_text(encoding="utf-8") == (
        second_original + "late concurrent change\n"
    )


def test_markdown_guard_preserves_mutation_at_replace_boundary(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    day.write_text(_entry("hfl-race", reference), encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    swap_names = migration._swap_names
    concurrent = day.read_text(encoding="utf-8") + "concurrent writer\n"

    def race(dir_fd, first_name, second_name):
        day.write_text(concurrent, encoding="utf-8")
        return swap_names(dir_fd, first_name, second_name)

    monkeypatch.setattr(migration, "_swap_names", race)

    try:
        migration._write_markdown_changes(corpus, scan.changes)
    except RuntimeError as exc:
        assert "Concurrent HFL corpus change" in str(exc)
    else:
        raise AssertionError("verify/replace races must fail closed")

    assert day.read_text(encoding="utf-8") == concurrent


def test_markdown_root_replacement_during_exchange_fails_and_restores(
    tmp_path,
    monkeypatch,
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    moved = tmp_path / "moved-corpus"
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-root-race", reference)
    day.write_text(original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    swap_names = migration._swap_names
    swaps = 0

    def replace_root_then_swap(dir_fd, first_name, second_name):
        nonlocal swaps
        swaps += 1
        if swaps == 1:
            corpus.rename(moved)
            corpus.mkdir()
        return swap_names(dir_fd, first_name, second_name)

    monkeypatch.setattr(migration, "_swap_names", replace_root_then_swap)

    try:
        migration._write_markdown_changes(corpus, scan.changes)
    except RuntimeError as exc:
        assert "corpus root changed" in str(exc)
    else:
        raise AssertionError("root substitution during publication must fail closed")

    assert not (corpus / day.name).exists()
    assert (moved / day.name).read_text(encoding="utf-8") == original


def test_markdown_replacement_preserves_filesystem_metadata(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    day.write_text(_entry("hfl-metadata", reference), encoding="utf-8")
    os.chmod(day, 0o640)
    timestamp_ns = 1_700_000_000_123_456_789
    os.utime(day, ns=(timestamp_ns, timestamp_ns))
    attribute = "com.harqis.test"
    subprocess.run(
        ["/usr/bin/xattr", "-w", attribute, "preserve-me", str(day)],
        check=True,
    )
    before = day.stat()

    migration._write_markdown_changes(corpus, migration.scan_markdown(corpus).changes)

    after = day.stat()
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert after.st_mtime_ns == before.st_mtime_ns
    assert subprocess.check_output(
        ["/usr/bin/xattr", "-p", attribute, str(day)],
        text=True,
    ).strip() == "preserve-me"


def test_rollback_does_not_overwrite_concurrent_post_publish_change(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    day.write_text(_entry("hfl-rollback-race", reference), encoding="utf-8")
    concurrent = "concurrent replacement\n"

    class Client:
        def scan_media(self, _index):
            return migration.ElasticsearchScan((), ())

        def update_sources(self, _changes, *, restore=False):
            if not restore:
                day.write_text(concurrent, encoding="utf-8")
                raise RuntimeError("simulated ES failure")

    try:
        migration.run_migration(
            corpus,
            Client(),
            index="hfl",
            apply=True,
            backup_root=tmp_path / "backups",
        )
    except RuntimeError as exc:
        assert "Markdown rollback failed" in str(exc)
    else:
        raise AssertionError("rollback must not overwrite a concurrent writer")

    assert day.read_text(encoding="utf-8") == concurrent


def test_cross_store_source_conflict_fails_closed(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    (corpus / "2026-07-26.md").write_text(
        _entry("hfl-conflict", reference), encoding="utf-8",
    )

    class ConflictingClient:
        def scan_media(self, _index):
            return migration.ElasticsearchScan((migration.ElasticsearchChange(
                index="hfl", doc_id="hfl-conflict", entry_id="hfl-conflict",
                old_source="media", new_source="android_capture",
                document={"entry_id": "hfl-conflict", "source": "media"},
            ),), ())

    try:
        migration.run_migration(corpus, ConflictingClient(), index="hfl")
    except RuntimeError as exc:
        assert "Cross-store source conflict" in str(exc)
    else:
        raise AssertionError("cross-store classification conflicts must fail closed")


def test_cross_store_changed_and_unresolved_ids_fail_closed():
    markdown_change = migration.MarkdownFileChange(
        path=Path("day.md"), original_text="", updated_text="",
        changes=(migration.SourceChange("hfl-split", "media", "desktop"),),
        identity=(1, 1, 0, 0, 0o600),
    )
    es_change = migration.ElasticsearchChange(
        index="hfl", doc_id="hfl-split", entry_id="hfl-split",
        old_source="media", new_source="desktop", document={},
        seq_no=1, primary_term=1,
    )
    cases = (
        (
            migration.MarkdownScan((markdown_change,), (), {"desktop": 1}),
            migration.ElasticsearchScan((), ("hfl-split",)),
        ),
        (
            migration.MarkdownScan((), ("hfl-split",), {}),
            migration.ElasticsearchScan((es_change,), ()),
        ),
    )

    for markdown, elasticsearch in cases:
        try:
            migration._validate_cross_store_sources(markdown, elasticsearch)
        except RuntimeError as exc:
            assert "Cross-store unresolved source conflict" in str(exc)
        else:
            raise AssertionError("changed/unresolved split-brain must fail closed")


def test_backup_creation_fsyncs_parent_directory(tmp_path):
    backup_root = tmp_path / "backups"
    corpus, corpus_fd = migration._open_directory_no_follow(tmp_path)
    try:
        target = migration._create_backup(
            corpus,
            migration.MarkdownScan((), (), {}),
            migration.ElasticsearchScan((), ()),
            backup_root,
            corpus_fd=corpus_fd,
        )
    finally:
        os.close(corpus_fd)

    assert target.is_dir()
    assert stat.S_IMODE(backup_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert (target / "manifest.json").is_file()


def test_es_scan_rejects_classified_document_without_concurrency_tokens():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )

    class Client(migration.ElasticsearchClient):
        metadata = {}

        def _request(self, method, path, body=None, **_kwargs):
            return {"hits": {"total": {"value": 1, "relation": "eq"}, "hits": [{
                "_index": "hfl", "_id": "hfl-no-token",
                "_source": {
                    "entry_id": "hfl-no-token", "source": "media",
                    "references": [reference],
                },
                **self.metadata,
            }]}}

    for metadata in ({}, {"_seq_no": 1}, {"_primary_term": 1}):
        client = Client("http://elasticsearch.invalid")
        client.metadata = metadata
        try:
            client.scan_media("hfl")
        except RuntimeError as exc:
            assert "concurrency metadata missing" in str(exc)
        else:
            raise AssertionError("missing ES concurrency metadata must fail closed")


def test_es_update_rejects_missing_concurrency_tokens_before_request():
    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **_kwargs):
            raise AssertionError("unsafe update must not reach Elasticsearch")

    change = migration.ElasticsearchChange(
        index="hfl", doc_id="doc", entry_id="hfl",
        old_source="media", new_source="desktop", document={"source": "media"},
    )

    try:
        Client("http://elasticsearch.invalid").update_sources((change,))
    except migration.BulkUpdateError as exc:
        assert "concurrency metadata missing" in str(exc)
        assert exc.applied_changes == ()
    else:
        raise AssertionError("unguarded ES updates must fail closed")


def test_es_bulk_uses_optimistic_concurrency_and_reports_partial_success():
    captured = {}

    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **kwargs):
            if path == "/_mget":
                return {"docs": [
                    {"_index": "hfl", "_id": "doc-1", "_source": {"source": "desktop"}},
                    {"_index": "hfl", "_id": "doc-2", "_source": {"source": "media"}},
                ]}
            captured.update(method=method, path=path, **kwargs)
            return {
                "errors": True,
                "items": [
                    {"update": {"status": 200, "result": "updated"}},
                    {"update": {"status": 409, "error": {"type": "version_conflict"}}},
                ],
            }

    changes = tuple(
        migration.ElasticsearchChange(
            index="hfl", doc_id=f"doc-{number}", entry_id=f"hfl-{number}",
            old_source="media", new_source="desktop",
            document={"source": "media"}, seq_no=number, primary_term=1,
        )
        for number in (1, 2)
    )
    try:
        Client("http://elasticsearch.invalid").update_sources(changes)
    except migration.BulkUpdateError as exc:
        assert exc.applied_changes == (changes[0],)
    else:
        raise AssertionError("partial bulk errors must be reported")

    payload = captured["raw_body"].decode("utf-8")
    assert '"if_seq_no":1' in payload
    assert '"if_primary_term":1' in payload


def test_es_bulk_malformed_later_item_preserves_confirmed_success():
    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **kwargs):
            if path == "/_mget":
                return {"docs": [
                    {"_index": "hfl", "_id": "doc-1", "_source": {"source": "desktop"}},
                    {"_index": "hfl", "_id": "doc-2", "_source": {"source": "media"}},
                ]}
            return {
                "errors": True,
                "items": [
                    {"update": {"status": 200, "result": "updated"}},
                    {"update": {"status": "not-an-integer"}},
                ],
            }

    changes = tuple(
        migration.ElasticsearchChange(
            index="hfl", doc_id=f"doc-{number}", entry_id=f"hfl-{number}",
            old_source="media", new_source="desktop", document={"source": "media"},
            seq_no=number, primary_term=1,
        )
        for number in (1, 2)
    )

    try:
        Client("http://elasticsearch.invalid").update_sources(changes)
    except migration.BulkUpdateError as exc:
        assert exc.applied_changes == (changes[0],)
        assert "malformed bulk response" in str(exc)
    else:
        raise AssertionError("malformed bulk item must preserve prior successes")


def test_es_bulk_is_bounded_and_retains_prior_batch_success_on_transport_error():
    calls = 0

    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **_kwargs):
            nonlocal calls
            if path == "/_mget":
                return {"docs": [{
                    "_index": "hfl", "_id": "doc-250",
                    "_source": {"source": "media"},
                }]}
            calls += 1
            if calls == 2:
                raise RuntimeError("transport failed")
            return {
                "errors": False,
                "items": [
                    {"update": {"status": 200, "result": "updated"}}
                    for _ in range(250)
                ],
            }

    changes = tuple(
        migration.ElasticsearchChange(
            index="hfl", doc_id=f"doc-{number}", entry_id=f"hfl-{number}",
            old_source="media", new_source="desktop", document={"source": "media"},
            seq_no=number, primary_term=1,
        )
        for number in range(251)
    )
    try:
        Client("http://elasticsearch.invalid").update_sources(changes)
    except migration.BulkUpdateError as exc:
        assert exc.applied_changes == changes[:250]
        assert "reconciled" in str(exc)
    else:
        raise AssertionError("transport failure must retain prior batch results")
    assert calls == 2


def test_es_bulk_malformed_later_response_retains_prior_batch_success():
    calls = 0

    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **_kwargs) -> Any:
            nonlocal calls
            if path == "/_mget":
                return {"docs": [{
                    "_index": "hfl", "_id": "doc-250",
                    "_source": {"source": "media"},
                }]}
            calls += 1
            if calls == 2:
                return []
            return {
                "errors": False,
                "items": [
                    {"update": {"status": 200, "result": "updated"}}
                    for _ in range(250)
                ],
            }

    changes = tuple(
        migration.ElasticsearchChange(
            index="hfl", doc_id=f"doc-{number}", entry_id=f"hfl-{number}",
            old_source="media", new_source="desktop", document={"source": "media"},
            seq_no=number, primary_term=1,
        )
        for number in range(251)
    )

    try:
        Client("http://elasticsearch.invalid").update_sources(changes)
    except migration.BulkUpdateError as exc:
        assert exc.applied_changes == changes[:250]
        assert "malformed bulk response" in str(exc)
    else:
        raise AssertionError("malformed later batches must retain prior successes")


def test_partial_es_failure_rolls_back_only_confirmed_updates(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-one", reference)
    day.write_text(original, encoding="utf-8")
    changes = (
        migration.ElasticsearchChange(
            index="hfl", doc_id="doc-one", entry_id="hfl-one",
            old_source="media", new_source="desktop",
            document={"entry_id": "hfl-one", "source": "media",
                      "references": [reference]},
        ),
        migration.ElasticsearchChange(
            index="hfl", doc_id="doc-two", entry_id="hfl-two",
            old_source="media", new_source="desktop",
            document={"entry_id": "hfl-two", "source": "media",
                      "references": [reference]},
        ),
    )

    class Client:
        def __init__(self):
            self.restored = ()

        def scan_media(self, _index):
            return migration.ElasticsearchScan(changes, ())

        def update_sources(self, submitted, *, restore=False):
            submitted = tuple(submitted)
            if restore:
                self.restored = submitted
                return submitted
            raise migration.BulkUpdateError("partial failure", (changes[0],))

        def verify_restored_documents(self, submitted):
            assert tuple(submitted) == self.restored

    client = Client()
    try:
        migration.run_migration(
            corpus, client, index="hfl", apply=True,
            backup_root=tmp_path / "backups",
        )
    except migration.BulkUpdateError:
        pass
    else:
        raise AssertionError("partial bulk failure must abort the migration")

    assert client.restored == (changes[0],)
    assert day.read_text(encoding="utf-8") == original


def test_post_publication_cleanup_failures_restore_markdown(tmp_path, monkeypatch):
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )

    for scenario in ("temporary", "guard", "fsync"):
        corpus = tmp_path / scenario
        corpus.mkdir()
        day = corpus / "2026-07-26.md"
        original = _entry(f"hfl-{scenario}", reference)
        day.write_text(original, encoding="utf-8")
        scan = migration.scan_markdown(corpus)

        with monkeypatch.context() as scoped:
            if scenario == "fsync":
                fsync = migration.os.fsync
                calls = 0

                def fail_fsync_once(descriptor):
                    nonlocal calls
                    calls += 1
                    if calls == 3:
                        raise OSError("injected cleanup fsync failure")
                    return fsync(descriptor)

                scoped.setattr(migration.os, "fsync", fail_fsync_once)
            else:
                unlink = migration.os.unlink
                failed = False
                marker = ".tmp-" if scenario == "temporary" else ".guard-"

                def fail_unlink_once(name, *, dir_fd=None):
                    nonlocal failed
                    if not failed and marker in str(name):
                        failed = True
                        raise OSError(f"injected {scenario} unlink failure")
                    return unlink(name, dir_fd=dir_fd)

                scoped.setattr(migration.os, "unlink", fail_unlink_once)

            try:
                migration._write_markdown_changes(corpus, scan.changes)
            except OSError as exc:
                assert "injected" in str(exc)
            else:
                raise AssertionError(f"{scenario} cleanup failure must abort")

        assert day.read_text(encoding="utf-8") == original


def test_prepublication_temp_failure_removes_private_artifacts(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-temp-cleanup", reference)
    day.write_text(original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)

    def fail_metadata_copy(_source_fd, _target_fd):
        raise OSError("injected metadata copy failure")

    monkeypatch.setattr(migration, "_copy_file_metadata", fail_metadata_copy)
    try:
        migration._write_markdown_changes(corpus, scan.changes)
    except OSError as exc:
        assert "metadata copy" in str(exc)
    else:
        raise AssertionError("temporary creation failure must abort")

    assert day.read_text(encoding="utf-8") == original
    assert not any(
        ".tmp-" in path.name or ".guard-" in path.name
        for path in corpus.iterdir()
    )


def test_offline_replace_is_explicit_and_applies_without_link_or_exchange(
    tmp_path,
    monkeypatch,
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-offline", reference)
    day.write_text(original, encoding="utf-8")

    def unavailable(*_args, **_kwargs):
        raise OSError(errno.ENOTSUP, "Operation not supported")

    monkeypatch.setattr(migration.os, "link", unavailable)
    try:
        migration._write_markdown_changes(
            corpus, migration.scan_markdown(corpus).changes,
        )
    except OSError as exc:
        assert exc.errno == errno.ENOTSUP
    else:
        raise AssertionError("normal mode must not silently relax publication safety")
    assert day.read_text(encoding="utf-8") == original

    migration._write_markdown_changes(
        corpus,
        migration.scan_markdown(corpus).changes,
        offline_replace=True,
    )
    assert "Source:          desktop" in day.read_text(encoding="utf-8")


def test_offline_replace_restores_after_post_publication_fsync_failure(
    tmp_path,
    monkeypatch,
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-offline-rollback", reference)
    day.write_text(original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    fsync = migration.os.fsync
    calls = 0

    def fail_first_directory_fsync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected offline publication fsync failure")
        return fsync(descriptor)

    monkeypatch.setattr(migration.os, "fsync", fail_first_directory_fsync)
    try:
        migration._write_markdown_changes(
            corpus, scan.changes, offline_replace=True,
        )
    except OSError as exc:
        assert "injected offline publication" in str(exc)
    else:
        raise AssertionError("post-publication failure must abort offline replace")

    assert day.read_text(encoding="utf-8") == original
    assert not any(".offline-" in path.name for path in corpus.iterdir())


def test_offline_path_swap_restores_retained_inode_without_touching_replacement(
    tmp_path, monkeypatch,
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day = corpus / "day.md"
    moved = corpus / "moved.md"
    original = "original\n"
    day.write_text(original, encoding="utf-8")
    identity = migration._file_identity(day.stat())
    replacement_times = (1_700_000_000_000_000_000, 1_700_000_001_000_000_000)
    write_payload = migration._write_fd_payload
    calls = 0

    def swap_after_write(file_fd, payload):
        nonlocal calls
        calls += 1
        write_payload(file_fd, payload)
        if calls == 1:
            day.rename(moved)
            day.write_text("replacement\n", encoding="utf-8")
            os.utime(day, ns=replacement_times)
            raise OSError("injected canonical path swap")

    monkeypatch.setattr(migration, "_write_fd_payload", swap_after_write)
    _root, corpus_fd = migration._open_directory_no_follow(corpus)
    try:
        try:
            migration._offline_in_place_write(
                day,
                "updated\n",
                dir_fd=corpus_fd,
                expected_text=original,
                expected_identity=identity,
            )
        except RuntimeError as exc:
            assert "retained inode was restored" in str(exc)
            assert "canonical path changed" in str(exc)
        else:
            raise AssertionError("canonical path swap must abort publication")
    finally:
        os.close(corpus_fd)

    replacement_stat = day.stat()
    assert replacement_stat.st_atime_ns == replacement_times[0]
    assert replacement_stat.st_mtime_ns == replacement_times[1]
    assert day.read_text(encoding="utf-8") == "replacement\n"
    assert moved.read_text(encoding="utf-8") == original


def test_multi_file_rollback_attempts_every_published_file(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    for number in (1, 2, 3):
        (corpus / f"2026-07-2{number}.md").write_text(
            _entry(f"hfl-{number}", reference), encoding="utf-8",
        )
    scan = migration.scan_markdown(corpus)
    calls = []

    def writer(path, _text, **kwargs):
        calls.append(path.name)
        if calls == [
            "2026-07-21.md", "2026-07-22.md", "2026-07-23.md",
        ]:
            raise OSError("publish failure")
        if calls[-2:] == ["2026-07-23.md", "2026-07-22.md"]:
            raise OSError("first rollback failure")
        return kwargs["expected_identity"]

    monkeypatch.setattr(migration, "_offline_in_place_write", writer)
    try:
        migration._write_markdown_changes(
            corpus, scan.changes, offline_replace=True,
        )
    except RuntimeError as exc:
        assert "rollback failures" in str(exc)
        assert "2026-07-22.md" in str(exc)
    else:
        raise AssertionError("publication and rollback failures must be aggregated")

    assert calls == [
        "2026-07-21.md",
        "2026-07-22.md",
        "2026-07-23.md",
        "2026-07-22.md",
        "2026-07-21.md",
    ]


def test_fenced_or_noncanonical_references_cannot_authorize_migration():
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    fenced = (
        "## 2026-07-26 19:59\n"
        "Source:          media\n"
        "Entry ID:        hfl-fenced\n"
        "Moment:          example only\n"
        "Tags:            #test\n"
        "```text\nReferences:\n"
        f"                 - {reference}\n```\n\n"
    )
    updated, changes, unresolved = migration.migrate_markdown_text(fenced)
    assert updated == fenced
    assert changes == ()
    assert unresolved == ("hfl-fenced",)

    narrative = fenced.replace(
        "Tags:            #test\n```text\n",
        f"References:\n                 - {reference}\nTags:            #test\n```text\n",
    )
    try:
        migration.migrate_markdown_text(narrative)
    except RuntimeError as exc:
        assert "canonical position" in str(exc)
    else:
        raise AssertionError("noncanonical narrative references must fail closed")


def test_truncated_bulk_response_retains_confirmed_success():
    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **kwargs):
            if path == "/_mget":
                return {"docs": [
                    {"_index": "hfl", "_id": "doc-1", "_source": {"source": "desktop"}},
                    {"_index": "hfl", "_id": "doc-2", "_source": {"source": "media"}},
                ]}
            return {
                "errors": False,
                "items": [{"update": {"status": 200, "result": "updated"}}],
            }

    changes = tuple(
        migration.ElasticsearchChange(
            index="hfl", doc_id=f"doc-{number}", entry_id=f"hfl-{number}",
            old_source="media", new_source="desktop", document={"source": "media"},
            seq_no=number, primary_term=1,
        )
        for number in (1, 2)
    )
    try:
        Client("http://elasticsearch.invalid").update_sources(changes)
    except migration.BulkUpdateError as exc:
        assert exc.applied_changes == (changes[0],)
        assert "reconciled" in str(exc)
    else:
        raise AssertionError("truncated bulk responses must require reconciliation")


def test_cross_store_validation_checks_non_media_counterparts():
    markdown_change = migration.MarkdownFileChange(
        path=Path("day.md"), original_text="", updated_text="",
        changes=(migration.SourceChange("hfl-split", "media", "desktop"),),
        identity=(1, 1, 0, 0, 0o600),
    )
    markdown = migration.MarkdownScan(
        (markdown_change,), (), {"desktop": 1}, {"hfl-split": "media"},
    )
    elasticsearch = migration.ElasticsearchScan(
        (), (), {"hfl-split": "android_capture"},
    )
    try:
        migration._validate_cross_store_sources(markdown, elasticsearch)
    except RuntimeError as exc:
        assert "Cross-store source conflict" in str(exc)
    else:
        raise AssertionError("non-media counterpart conflicts must fail closed")


def test_es_scan_rejects_duplicate_ids_across_non_media_documents():
    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **kwargs):
            return {"hits": {"total": {"value": 2, "relation": "eq"}, "hits": [
                {"_index": "hfl", "_id": "one", "_source": {"entry_id": "duplicate", "source": "desktop"}},
                {"_index": "hfl", "_id": "two", "_source": {"entry_id": "duplicate", "source": "android_capture"}},
            ]}}

    try:
        Client("http://elasticsearch.invalid").scan_media("hfl")
    except RuntimeError as exc:
        assert "Duplicate Elasticsearch HFL entry ID" in str(exc)
    else:
        raise AssertionError("duplicates outside legacy media must fail closed")


def test_backup_root_symlink_is_rejected(tmp_path):
    corpus, corpus_fd = migration._open_directory_no_follow(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "backups"
    link.symlink_to(outside, target_is_directory=True)
    try:
        try:
            migration._create_backup(
                corpus,
                migration.MarkdownScan((), (), {}),
                migration.ElasticsearchScan((), ()),
                link,
                corpus_fd=corpus_fd,
            )
        except OSError:
            pass
        else:
            raise AssertionError("symlinked backup roots must fail closed")
    finally:
        os.close(corpus_fd)
    assert not tuple(outside.iterdir())


def test_transport_failure_reconciles_updates_committed_before_timeout():
    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **kwargs):
            if path == "/_bulk":
                raise RuntimeError("timeout after commit")
            if path == "/_mget":
                return {"docs": [
                    {"_index": "hfl", "_id": "doc-1", "_source": {"source": "desktop"}},
                    {"_index": "hfl", "_id": "doc-2", "_source": {"source": "desktop"}},
                ]}
            raise AssertionError(path)

    changes = tuple(
        migration.ElasticsearchChange(
            index="hfl", doc_id=f"doc-{number}", entry_id=f"hfl-{number}",
            old_source="media", new_source="desktop", document={"source": "media"},
            seq_no=number, primary_term=1,
        )
        for number in (1, 2)
    )
    try:
        Client("http://elasticsearch.invalid").update_sources(changes)
    except migration.BulkUpdateError as exc:
        assert exc.applied_changes == changes
        assert "reconciled" in str(exc)
    else:
        raise AssertionError("transport ambiguity must abort with reconciled state")


def test_run_migration_offline_es_failure_restores_both_stores(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-offline-es-failure", reference)
    day.write_text(original, encoding="utf-8")
    es_change = migration.ElasticsearchChange(
        index="hfl", doc_id="hfl-offline-es-failure",
        entry_id="hfl-offline-es-failure", old_source="media",
        new_source="desktop", document={"source": "media", "references": [reference]},
        seq_no=1, primary_term=1,
    )

    class Client:
        restores = []

        def scan_media(self, index):
            assert index == "harqis-hfl-entries"
            return migration.ElasticsearchScan(
                (es_change,), (), {"hfl-offline-es-failure": "media"},
            )

        def update_sources(self, changes, *, restore=False):
            self.restores.append(restore)
            if not restore:
                raise migration.BulkUpdateError("injected ES failure", tuple(changes))
            return tuple(changes)

        def verify_restored_documents(self, changes):
            assert tuple(changes) == (es_change,)

    client = Client()
    try:
        migration.run_migration(
            corpus,
            client,
            apply=True,
            offline_exfat=True,
            backup_root=tmp_path / "backups",
        )
    except migration.BulkUpdateError:
        pass
    else:
        raise AssertionError("ES failure must abort the offline transaction")
    assert day.read_text(encoding="utf-8") == original
    assert client.restores == [False, True]


def test_offline_in_place_write_never_touches_foreign_temp_like_file(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day = corpus / "day.md"
    original = "original\n"
    day.write_text(original, encoding="utf-8")
    identity = migration._file_identity(day.stat())
    collision = corpus / f".day.md.offline-tmp-{os.getpid()}-fixed"
    collision.write_text("foreign\n", encoding="utf-8")
    _root, corpus_fd = migration._open_directory_no_follow(corpus)
    try:
        migration._offline_in_place_write(
            day,
            "updated\n",
            mode=0o600,
            dir_fd=corpus_fd,
            expected_text=original,
            expected_identity=identity,
        )
    finally:
        os.close(corpus_fd)
    assert day.read_text(encoding="utf-8") == "updated\n"
    assert collision.read_text(encoding="utf-8") == "foreign\n"


def test_cli_forwards_offline_exfat_flag(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        migration,
        "elasticsearch_client_from_env",
        lambda: object(),
    )

    def run(corpus, client, **kwargs):
        captured.update(corpus=corpus, client=client, **kwargs)
        return migration.MigrationSummary(0, 0, 0, 0, 0, {}, False)

    monkeypatch.setattr(migration, "run_migration", run)
    assert migration.main(["--corpus", str(tmp_path), "--offline-exfat"]) == 0
    assert captured["offline_exfat"] is True


def test_unknown_es_batch_compensates_every_attempted_document(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-unknown-es", reference)
    day.write_text(original, encoding="utf-8")
    es_change = migration.ElasticsearchChange(
        index="hfl", doc_id="hfl-unknown-es", entry_id="hfl-unknown-es",
        old_source="media", new_source="desktop",
        document={"source": "media", "references": [reference]},
        seq_no=1, primary_term=1,
    )

    class Client(migration.ElasticsearchClient):
        source = "media"
        bulk_calls = 0

        def scan_media(self, index):
            assert index == "harqis-hfl-entries"
            return migration.ElasticsearchScan(
                (es_change,), (), {"hfl-unknown-es": "media"},
            )

        def _request(self, method, path, body=None, **kwargs):
            if path == "/_mget":
                return {"malformed": True}
            if path == "/_bulk":
                self.bulk_calls += 1
                if self.bulk_calls == 1:
                    self.source = "desktop"
                    raise RuntimeError("timeout after commit")
                self.source = "media"
                return {"errors": False, "items": [
                    {"update": {"status": 200, "result": "updated"}},
                ]}
            raise AssertionError(path)

    client = Client("http://elasticsearch.invalid")
    try:
        migration.run_migration(
            corpus,
            client,
            apply=True,
            offline_exfat=True,
            backup_root=tmp_path / "backups",
        )
    except RuntimeError as exc:
        assert "rollback incomplete" in str(exc)
        assert "rollback verification was malformed" in str(exc)
    else:
        raise AssertionError("unknown initial bulk state must abort after compensation")
    assert day.read_text(encoding="utf-8") == original
    assert client.source == "media"
    assert client.bulk_calls == 2


def test_es_scan_rejects_timeout_failed_shards_and_incomplete_total():
    responses = (
        {
            "timed_out": True,
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "_shards": {"failed": 1},
            "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        },
        {
            "hits": {"total": {"value": 2, "relation": "eq"}, "hits": []},
        },
        {
            "hits": {"total": {"value": 2, "relation": "gte"}, "hits": []},
        },
    )

    class Client(migration.ElasticsearchClient):
        response = {}

        def _request(self, method, path, body=None, **kwargs):
            return self.response

    for response in responses:
        client = Client("http://elasticsearch.invalid")
        client.response = response
        try:
            client.scan_media("hfl")
        except RuntimeError:
            pass
        else:
            raise AssertionError("partial Elasticsearch scans must fail closed")


def test_backup_binding_change_aborts_before_apply(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    backup_root = tmp_path / "backups"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_write = migration._write_bytes_fsync_at
    moved = tmp_path / "moved-backup"

    def race(descriptor, name, payload, **kwargs):
        original_write(descriptor, name, payload, **kwargs)
        if name != "manifest.json":
            return
        target = next(path for path in backup_root.iterdir() if path.is_dir())
        target.rename(moved)
        target.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(migration, "_write_bytes_fsync_at", race)
    _root, corpus_fd = migration._open_directory_no_follow(corpus)
    try:
        try:
            migration._create_backup(
                corpus,
                migration.MarkdownScan((), (), {}),
                migration.ElasticsearchScan((), ()),
                backup_root,
                corpus_fd=corpus_fd,
            )
        except RuntimeError as exc:
            assert "root changed" in str(exc)
        else:
            raise AssertionError("replaced backup publication paths must fail closed")
    finally:
        os.close(corpus_fd)
    assert (moved / "manifest.json").is_file()
    assert not (outside / "manifest.json").exists()


def test_es_scan_rejects_malformed_source_hit():
    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **kwargs):
            return {"hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [{"_index": "hfl", "_id": "bad", "_source": None}],
            }}

    try:
        Client("http://elasticsearch.invalid").scan_media("hfl")
    except RuntimeError as exc:
        assert "valid _source" in str(exc)
    else:
        raise AssertionError("malformed Elasticsearch hits must fail closed")


def test_backup_binding_is_retained_until_transaction_finishes(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-backup-retained", reference)
    day.write_text(original, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = tmp_path / "moved-backup"
    real_create = migration._create_backup

    def race(*args, **kwargs):
        result = real_create(*args, **kwargs)
        assert isinstance(result, tuple)
        target, descriptor = result
        target.rename(moved)
        target.symlink_to(outside, target_is_directory=True)
        return target, descriptor

    monkeypatch.setattr(migration, "_create_backup", race)

    class Client:
        updated = False

        def scan_media(self, index):
            assert index == "harqis-hfl-entries"
            return migration.ElasticsearchScan((), (), {})

        def update_sources(self, changes, *, restore=False):
            self.updated = True
            return tuple(changes)

    client = Client()
    try:
        migration.run_migration(
            corpus,
            client,
            apply=True,
            offline_exfat=True,
            backup_root=tmp_path / "backups",
        )
    except RuntimeError as exc:
        assert "root changed" in str(exc)
    else:
        raise AssertionError("post-return backup substitution must abort apply")
    assert day.read_text(encoding="utf-8") == original
    assert client.updated is False
    assert (moved / "manifest.json").is_file()


def test_run_migration_changes_only_taxonomy_not_es_metadata(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    entry_id = "hfl-taxonomy-only"
    original = _entry(entry_id, reference)
    expected, _, _ = migration.migrate_markdown_text(original)
    day = corpus / "2026-07-26.md"
    day.write_text(original, encoding="utf-8")
    document = {
        "entry_id": entry_id,
        "source": "media",
        "when": "2026-07-26T19:59:40.050000",
        "synthesized": True,
        "references": [reference],
    }
    es_change = migration.ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id=entry_id,
        entry_id=entry_id,
        old_source="media",
        new_source="desktop",
        document=document,
    )

    class Client:
        def __init__(self):
            self.source = "media"

        def scan_media(self, index):
            assert index == "harqis-hfl-entries"
            if self.source != "media":
                return migration.ElasticsearchScan(
                    (), (), {entry_id: "desktop"},
                )
            return migration.ElasticsearchScan(
                (es_change,), (), {entry_id: "media"}
            )

        def update_sources(self, changes, *, restore=False):
            self.source = "media" if restore else "desktop"
            return tuple(changes)

        def verify_updated_documents(self, changes):
            assert self.source == "desktop"
            assert tuple(changes) == (es_change,)

    migration.run_migration(
        corpus,
        Client(),
        apply=True,
        offline_exfat=True,
        backup_root=tmp_path / "backups",
    )

    migrated = day.read_text(encoding="utf-8")
    assert migrated == expected
    assert "## 2026-07-26 19:59\n" in migrated
    assert "Synthesized:" not in migrated


def test_exact_source_renames_are_allowlisted_and_canonical():
    approved = {
        "android_capture": "android-capture",
        "echomtg_inventory": "echomtg-inventory",
    }
    assert migration._validated_source_renames(approved) == approved
    for invalid in (
        {"android_capture": "android_capture"},
        {"android_capture": "android-capture\nspoofed"},
        {"other_source": "other-source"},
    ):
        try:
            migration._validated_source_renames(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("unapproved or noncanonical renames must fail closed")


def test_descriptor_exhaustion_before_publication_leaves_markdown_unchanged(
    tmp_path, monkeypatch,
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/"
        "windows-work-all-daily-dumps-2026-07-26/archive/"
        "sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-dup-before-publish", reference)
    day.write_text(original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    real_dup = os.dup
    calls = 0

    def fail_retained_descriptor(file_fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EMFILE, "injected descriptor exhaustion")
        return real_dup(file_fd)

    with migration._markdown_locks(corpus, scan.changes) as (changes, corpus_fd):
        monkeypatch.setattr(os, "dup", fail_retained_descriptor)
        try:
            migration._write_markdown_changes(
                corpus,
                changes,
                locks_held=True,
                corpus_fd=corpus_fd,
            )
        except OSError as exc:
            assert exc.errno == errno.EMFILE
        else:
            raise AssertionError("descriptor exhaustion must abort before publication")

    assert day.read_text(encoding="utf-8") == original


def test_elasticsearch_postflight_rejects_non_source_document_drift():
    original = {
        "entry_id": "hfl-postflight-drift",
        "source": "android_capture",
        "when": "2026-08-01T12:00:00",
        "moment": "capture",
    }
    change = migration.ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="hfl-postflight-drift",
        entry_id="hfl-postflight-drift",
        old_source="android_capture",
        new_source="android-capture",
        document=original,
    )

    class Client(migration.ElasticsearchClient):
        def _request(self, method, path, body=None, **kwargs):
            assert (method, path) == ("POST", "/_mget")
            current = dict(original)
            current["source"] = "android-capture"
            current["when"] = "2026-08-01T12:01:00"
            return {"docs": [{
                "_index": "harqis-hfl-entries",
                "_id": "hfl-postflight-drift",
                "_source": current,
            }]}

    try:
        Client("http://elasticsearch.invalid").verify_updated_documents((change,))
    except RuntimeError as exc:
        assert "postflight mismatch" in str(exc)
    else:
        raise AssertionError("postflight must reject non-source document drift")


def test_postflight_drift_reports_manual_recovery_after_transaction_rollback(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = "/Volumes/harqis-data/dumps/nothing-phone/DCIM/Camera/photo.jpg"
    day = corpus / "2026-08-01.md"
    original_text = _entry(
        "hfl-postflight-transaction", reference, source="android_capture",
    )
    day.write_text(original_text, encoding="utf-8")
    original_document = {
        "entry_id": "hfl-postflight-transaction",
        "source": "android_capture",
        "when": "2026-08-01T12:00:00",
        "references": [reference],
    }
    change = migration.ElasticsearchChange(
        index="hfl", doc_id="hfl-postflight-transaction",
        entry_id="hfl-postflight-transaction", old_source="android_capture",
        new_source="android-capture", document=dict(original_document),
    )

    class Client:
        def __init__(self):
            self.document = dict(original_document)

        def scan_media(self, _index, *, source_renames=None):
            assert source_renames == {"android_capture": "android-capture"}
            if self.document["source"] == "android_capture":
                return migration.ElasticsearchScan(
                    (change,), (), {change.entry_id: "android_capture"},
                )
            return migration.ElasticsearchScan(
                (), (), {change.entry_id: "android-capture"},
            )

        def update_sources(self, changes, *, restore=False):
            assert tuple(changes) == (change,)
            self.document["source"] = "android_capture" if restore else "android-capture"

        def verify_updated_documents(self, changes):
            assert tuple(changes) == (change,)
            self.document["when"] = "2026-08-01T12:01:00"
            raise RuntimeError("Elasticsearch postflight mismatch")

        def verify_restored_documents(self, changes):
            assert tuple(changes) == (change,)
            if self.document != original_document:
                raise RuntimeError(
                    "manual recovery required for Elasticsearch documents: "
                    + change.entry_id
                )

    client = Client()
    try:
        migration.run_migration(
            corpus, client, index="hfl", apply=True, offline_exfat=True,
            backup_root=tmp_path / "backups",
            source_renames={"android_capture": "android-capture"},
        )
    except RuntimeError as exc:
        assert "Elasticsearch rollback incomplete" in str(exc)
        assert "manual recovery required" in str(exc)
        assert str(tmp_path / "backups") in str(exc)
    else:
        raise AssertionError("postflight drift must fail the full transaction")
    assert day.read_text(encoding="utf-8") == original_text
    assert client.document["source"] == "android_capture"
    assert client.document["when"] == "2026-08-01T12:01:00"


def test_offline_apply_acquires_corpus_wide_quiescence_lock(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    events = []

    class Lock:
        def __enter__(self):
            events.append("entered")

        def __exit__(self, *_args):
            events.append("exited")

    monkeypatch.setattr(
        migration, "corpus_write_lock",
        lambda root, timeout: (events.append((Path(root), timeout)) or Lock()),
    )

    class Client:
        def scan_media(self, _index):
            assert events[-1] == "entered"
            return migration.ElasticsearchScan((), (), {})

    migration.run_migration(
        corpus, Client(), apply=True, offline_exfat=True,
        backup_root=tmp_path / "backups",
    )
    assert events == [(corpus.resolve(), 120), "entered", "exited"]


def test_offline_later_file_failure_restores_appledouble_sidecars(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/windows-work-all-daily-dumps-2026-07-26/"
        "archive/sc-desktop-check_monitor1.jpg"
    )
    files = [corpus / "2026-07-25.md", corpus / "2026-07-26.md"]
    originals = {}
    sidecars = {}
    for index, path in enumerate(files):
        text = _entry(f"hfl-sidecar-{index}", reference)
        path.write_text(text, encoding="utf-8")
        sidecar = path.with_name(f"._{path.name}")
        payload = f"appledouble-{index}".encode()
        sidecar.write_bytes(payload)
        originals[path] = text
        sidecars[sidecar] = payload

    real_writer = migration._offline_in_place_write
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EIO, "injected later-file failure")
        return real_writer(*args, **kwargs)

    monkeypatch.setattr(migration, "_offline_in_place_write", fail_second)
    try:
        migration._write_markdown_changes(
            corpus, migration.scan_markdown(corpus).changes,
            offline_replace=True,
        )
    except OSError as exc:
        assert exc.errno == errno.EIO
    else:
        raise AssertionError("later-file failure must abort the offline write")
    for path, text in originals.items():
        assert path.read_text(encoding="utf-8") == text
    for path, payload in sidecars.items():
        assert path.read_bytes() == payload
    assert not [path for path in corpus.iterdir() if "offline-" in path.name]


def test_offline_partial_write_restores_bytes_and_metadata(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/windows-work-all-daily-dumps-2026-07-26/"
        "archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    original = _entry("hfl-partial-write", reference)
    day.write_text(original, encoding="utf-8")
    scan = migration.scan_markdown(corpus)
    source_fd = os.open(day, os.O_RDONLY)
    try:
        original_metadata = migration._backup_metadata(source_fd)
    finally:
        os.close(source_fd)
    real_write = migration._write_fd_payload
    calls = 0

    def partial_once(file_fd, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            os.lseek(file_fd, 0, os.SEEK_SET)
            os.write(file_fd, payload[:7])
            os.fsync(file_fd)
            raise OSError(errno.EIO, "injected partial write")
        return real_write(file_fd, payload)

    monkeypatch.setattr(migration, "_write_fd_payload", partial_once)
    try:
        migration._write_markdown_changes(
            corpus, scan.changes, offline_replace=True,
        )
    except OSError as exc:
        assert exc.errno == errno.EIO
    else:
        raise AssertionError("partial write must fail")
    target_fd = os.open(day, os.O_RDONLY)
    try:
        assert migration._backup_metadata(target_fd) == original_metadata
    finally:
        os.close(target_fd)
    assert day.read_text(encoding="utf-8") == original


def test_acl_and_complete_metadata_survive_publication(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    reference = (
        "/Volumes/harqis-data/dumps/windows-work-all-daily-dumps-2026-07-26/"
        "archive/sc-desktop-check_monitor1.jpg"
    )
    day = corpus / "2026-07-26.md"
    day.write_text(_entry("hfl-acl", reference), encoding="utf-8")
    result = subprocess.run(
        ["chmod", "+a", "everyone allow read", str(day)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return
    source_fd = os.open(day, os.O_RDONLY)
    try:
        before = migration._backup_metadata(source_fd)
    finally:
        os.close(source_fd)
    assert before["acl"]
    migration._write_markdown_changes(corpus, migration.scan_markdown(corpus).changes)
    target_fd = os.open(day, os.O_RDONLY)
    try:
        after = migration._backup_metadata(target_fd)
    finally:
        os.close(target_fd)
    assert after == before
    subprocess.run(["chmod", "-N", str(day)], check=True)
