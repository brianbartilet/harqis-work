from __future__ import annotations

import json

import pytest

from scripts.agents.hfl.migrate_references import (
    ElasticsearchChange,
    migrate_markdown_text,
    run_migration,
    safe_report_id,
)


class FakeElasticsearch:
    def __init__(self, changes=(), *, fail_updates=False):
        self.changes = list(changes)
        self.fail_updates = fail_updates
        self.updates = []

    def scan(self, index):
        return self.changes

    def update_references(self, changes, *, restore=False):
        self.updates.append((tuple(changes), restore))
        if self.fail_updates and not restore:
            raise RuntimeError("update failed")


def _markdown() -> str:
    return (
        "## 2026-07-26 10:00\n"
        "Entry ID:        hfl-http-only\n"
        "Moment:          HTTP only\n"
        "References:\n"
        "                 - http://internal.example/dashboard\n"
        "\n"
        "## 2026-07-26 09:00\n"
        "Entry ID:        hfl-mixed\n"
        "Moment:          Mixed references\n"
        "References:\n"
        "                 - HTTP://example.com/insecure\n"
        "                 - https://example.com/secure\n"
        "                 - /Users/harqis-one/GIT/notes/file.md\n"
        "\n"
    )


def test_migrate_markdown_removes_http_and_preserves_other_bytes():
    updated, entry_ids, removed = migrate_markdown_text(_markdown())

    assert removed == 2
    assert entry_ids == ("hfl-http-only", "hfl-mixed")
    assert "http://" not in updated.casefold()
    assert updated.count("References:") == 1
    assert "https://example.com/secure" in updated
    assert "/Users/harqis-one/GIT/notes/file.md" in updated
    assert "Moment:          HTTP only" in updated


def test_migration_report_ids_cannot_inject_paths_or_terminal_controls():
    assert safe_report_id("../../secret\n\u001b[31m") == "..-..-secret-31m"


def test_migration_dry_run_changes_neither_store_nor_creates_backup(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-07-26.md"
    day_file.write_text(_markdown(), encoding="utf-8")
    es_change = ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="doc-1",
        source={
            "entry_id": "hfl-mixed",
            "references": [
                "http://example.com/insecure",
                "https://example.com/secure",
            ],
        },
        updated_references=("https://example.com/secure",),
        entry_id="hfl-mixed",
        removed=1,
    )
    client = FakeElasticsearch([es_change])
    backup_root = tmp_path / "backups"

    summary = run_migration(
        corpus,
        client,
        apply=False,
        backup_root=backup_root,
    )

    assert summary.applied is False
    assert summary.markdown_files == 1
    assert summary.elasticsearch_documents == 1
    assert summary.references_removed == 3
    assert summary.entry_ids == ("hfl-http-only", "hfl-mixed")
    assert day_file.read_text(encoding="utf-8") == _markdown()
    assert client.updates == []
    assert not backup_root.exists()


def test_migration_apply_backs_up_and_updates_both_stores(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-07-26.md"
    day_file.write_text(_markdown(), encoding="utf-8")
    es_change = ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="doc-1",
        source={
            "entry_id": "hfl-mixed",
            "references": [
                "http://example.com/insecure",
                "https://example.com/secure",
            ],
        },
        updated_references=("https://example.com/secure",),
        entry_id="hfl-mixed",
        removed=1,
    )
    client = FakeElasticsearch([es_change])

    summary = run_migration(
        corpus,
        client,
        apply=True,
        backup_root=tmp_path / "backups",
    )

    assert summary.applied is True
    assert "http://" not in day_file.read_text(encoding="utf-8").casefold()
    assert client.updates == [((es_change,), False)]
    assert summary.backup_dir is not None
    assert (summary.backup_dir / "markdown" / day_file.name).read_text(
        encoding="utf-8"
    ) == _markdown()
    es_backup = json.loads(
        (summary.backup_dir / "elasticsearch.json").read_text(encoding="utf-8")
    )
    assert es_backup[0]["_source"] == es_change.source


def test_migration_rolls_back_when_elasticsearch_update_fails(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-07-26.md"
    day_file.write_text(_markdown(), encoding="utf-8")
    change = ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="doc-1",
        source={"entry_id": "hfl-mixed", "references": ["http://example.com"]},
        updated_references=(),
        entry_id="hfl-mixed",
        removed=1,
    )
    client = FakeElasticsearch([change], fail_updates=True)

    with pytest.raises(RuntimeError, match="update failed"):
        run_migration(
            corpus,
            client,
            apply=True,
            backup_root=tmp_path / "backups",
        )

    assert day_file.read_text(encoding="utf-8") == _markdown()
    assert client.updates[-1] == ((change,), True)
