from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import scripts.agents.hfl.migrate_noncanonical_h2 as migration
from scripts.agents.hfl.migrate_noncanonical_h2 import (
    ElasticsearchBulkError,
    ElasticsearchChange,
    ElasticsearchClient,
    ElasticsearchWrite,
    migrate_markdown_text,
    migrate_what_happened,
    run_migration,
    scan_markdown,
)


def test_migrate_markdown_demotes_nested_h2_in_agent_session_entry():
    original = (
        "## 2026-05-21 10:00\n"
        "Moment:          Historical session\n"
        "What happened:\n"
        "### Request\n"
        "Show the migration.\n\n"
        "### Outcome\n"
        "Result details.\n\n"
        "## Active Task\n"
        "Finished the repair.\n"
        "Source:          agent-session\n"
        "Entry ID:        agent-example\n\n"
        "## 2026-05-21 09:00\n"
        "Moment:          Canonical neighbor\n"
        "Source:          git\n"
        "Entry ID:        git-example\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert updated.startswith("## 2026-05-21 10:00\n")
    assert "### Active Task\n" in updated
    assert re.search(r"^## Active Task$", updated, re.MULTILINE) is None
    assert "## 2026-05-21 09:00\n" in updated
    assert entry_ids == ("agent-example",)
    assert demoted == 1


def test_migrate_markdown_preserves_fenced_h2_and_non_agent_entries():
    original = (
        "## 2026-05-21 10:00\n"
        "What happened:\n"
        "```markdown\n"
        "## Example inside a fence\n"
        "```\n"
        "## Visible nested heading\n"
        "Source:          agent-session\n"
        "Entry ID:        agent-example\n\n"
        "## 2026-05-21 09:00\n"
        "What happened:\n"
        "## Git narrative heading\n"
        "Source:          git\n"
        "Entry ID:        git-example\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert re.search(r"^## Example inside a fence$", updated, re.MULTILINE)
    assert "### Visible nested heading\n" in updated
    assert re.search(r"^## Git narrative heading$", updated, re.MULTILINE)
    assert entry_ids == ("agent-example",)
    assert demoted == 1


def test_scan_markdown_limits_scope_to_visible_daily_files(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    daily = corpus / "2026-05-21.md"
    daily.write_text(
        "## 2026-05-21 10:00\n"
        "What happened:\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: agent-example\n",
        encoding="utf-8",
    )
    (corpus / "2026-W21-rollup.md").write_text(daily.read_text(), encoding="utf-8")
    (corpus / "._2026-05-21.md").write_bytes(b"\x00\x05\x16\x07")

    changes = scan_markdown(corpus)

    assert [change.path for change in changes] == [daily]
    assert changes[0].headings_demoted == 1


def test_migrate_markdown_recovers_after_truncated_fence_at_field_boundary():
    original = (
        "## 2026-07-19 10:00\n"
        "What happened:\n"
        "```text\n"
        "~/storage/shared/Andr\n"
        "Why it stayed: Truncated historical outcome.\n"
        "Possible use: audit-log\n"
        "## Active Task\n"
        "Finished the repair.\n"
        "Source: agent-session\n"
        "Entry ID: agent-example\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert "```text\n~/storage/shared/Andr\n" in updated
    assert "### Active Task\n" in updated
    assert entry_ids == ("agent-example",)
    assert demoted == 1


def test_truncated_fence_stops_at_next_canonical_entry():
    original = (
        "## 2026-07-19 10:00\n"
        "Source: agent-session\nEntry ID: first\nWhat happened:\n"
        "```text\n## Still fenced\n"
        "## 2026-07-19 11:00\n"
        "Source: agent-session\nEntry ID: second\nWhat happened:\n"
        "## Visible heading\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert "## Still fenced\n" in updated
    assert "## 2026-07-19 11:00\n" in updated
    assert "### Visible heading\n" in updated
    assert entry_ids == ("second",)
    assert demoted == 1


def test_canonical_date_heading_inside_valid_fence_is_not_an_entry_boundary():
    original = (
        "## 2026-07-19 10:00\n"
        "What happened:\n"
        "```markdown\n"
        "## 2026-07-18 09:00\n"
        "Source: git\n"
        "Entry ID: example-in-code\n"
        "```\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: real-entry\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert "## 2026-07-18 09:00\n" in updated
    assert "### Active Task\n" in updated
    assert entry_ids == ("real-entry",)
    assert demoted == 1


def test_valid_fence_is_not_recovered_at_field_shaped_content():
    original = (
        "## 2026-07-19 10:00\n"
        "What happened:\n"
        "```text\n"
        "Why it stayed: this is example content\n"
        "## Example heading\n"
        "Source: agent-session\n"
        "Entry ID: example-in-code\n"
        "```\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: real-entry\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert "## Example heading\n" in updated
    assert "### Active Task\n" in updated
    assert entry_ids == ("real-entry",)
    assert demoted == 1


@pytest.mark.parametrize("invalid_close", ["````\n", "~~~ trailing\n", "~~\n"])
def test_only_valid_matching_markdown_fence_closes_code_block(invalid_close):
    original = (
        "~~~text\n"
        "## Fenced heading\n"
        f"{invalid_close}"
        "## Still fenced\n"
        "~~~   \n"
        "## Visible heading\n"
    )

    updated, demoted = migrate_what_happened(original)

    assert "## Fenced heading\n" in updated
    assert "## Still fenced\n" in updated
    assert "### Visible heading\n" in updated
    assert demoted == 1


def test_fenced_source_and_entry_id_do_not_classify_entry():
    original = (
        "## 2026-07-19 10:00\n"
        "What happened:\n"
        "```text\n"
        "Source: agent-session\n"
        "Entry ID: fake-entry\n"
        "```\n"
        "## Must remain unchanged\n"
        "Source: git\n"
        "Entry ID: real-git-entry\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert updated == original
    assert entry_ids == ()
    assert demoted == 0


def test_narrative_field_examples_do_not_override_leading_metadata():
    original = (
        "## 2026-07-19 10:00\n"
        "Source: agent-session\n"
        "Entry ID: real-entry\n"
        "What happened:\n"
        "## Active Task\n"
        "Source: git\n"
        "Entry ID: illustrative-only\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert "### Active Task\n" in updated
    assert entry_ids == ("real-entry",)
    assert demoted == 1


def test_agent_session_shaped_example_inside_valid_fence_is_preserved():
    original = (
        "## 2026-07-19 10:00\nWhat happened:\n"
        "```markdown\n## 2026-07-18 09:00\n## Example heading\n"
        "Source: agent-session\nEntry ID: example-in-code\n```\n"
        "## Active Task\nSource: agent-session\nEntry ID: real-entry\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert "## Example heading\n" in updated
    assert "### Active Task\n" in updated
    assert entry_ids == ("real-entry",)
    assert demoted == 1


def test_trailing_canonical_metadata_wins_over_narrative_field_example():
    original = (
        "## 2026-07-19 10:00\n"
        "What happened:\n"
        "Source: git\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: real-entry\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)

    assert "### Active Task\n" in updated
    assert entry_ids == ("real-entry",)
    assert demoted == 1


def test_markdown_migration_is_idempotent():
    original = (
        "## 2026-07-19 10:00\n"
        "What happened:\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: real-entry\n"
    )

    updated, entry_ids, demoted = migrate_markdown_text(original)
    rerun, rerun_entry_ids, rerun_demoted = migrate_markdown_text(updated)

    assert entry_ids == ("real-entry",)
    assert demoted == 1
    assert rerun == updated
    assert rerun_entry_ids == ()
    assert rerun_demoted == 0


def test_migrate_what_happened_demotes_visible_h2_only():
    original = (
        "### Outcome\n"
        "## Visible heading\n"
        "~~~text\n"
        "## Fenced heading\n"
        "~~~\n"
    )

    updated, demoted = migrate_what_happened(original)

    assert "### Outcome\n" in updated
    assert "### Visible heading\n" in updated
    assert re.search(r"^## Fenced heading$", updated, re.MULTILINE)
    assert demoted == 1


def test_scan_markdown_rejects_symlinked_daily_file(tmp_path):
    corpus = tmp_path / "corpus"
    outside = tmp_path / "outside.md"
    corpus.mkdir()
    outside.write_text(
        "## 2026-07-19 10:00\n## Active Task\nSource: agent-session\n",
        encoding="utf-8",
    )
    (corpus / "2026-07-19.md").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        scan_markdown(corpus)


def test_scan_markdown_rejects_symlinked_directory_component(tmp_path):
    corpus = tmp_path / "corpus"
    outside = tmp_path / "outside"
    corpus.mkdir()
    outside.mkdir()
    (outside / "2026-07-19.md").write_text("irrelevant", encoding="utf-8")
    (corpus / "archive").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        scan_markdown(corpus)


class FakeElasticsearch:
    def __init__(self, changes=(), *, fail_updates=False, fail_restore=False):
        self.changes = list(changes)
        self.fail_updates = fail_updates
        self.fail_restore = fail_restore
        self.updates = []
        self.revalidations = []

    def scan(self, index):
        return self.changes

    def revalidate(self, changes):
        self.revalidations.append(tuple(changes))

    def update_what_happened(self, changes, *, restore=False):
        changes = tuple(changes)
        self.updates.append((changes, restore))
        if self.fail_updates and not restore:
            raise RuntimeError("update failed")
        if self.fail_restore and restore:
            raise RuntimeError("restore failed")
        if restore:
            return ()
        return tuple(
            ElasticsearchWrite(change, 10 + index, 1)
            for index, change in enumerate(changes)
        )


def test_migration_dry_run_reports_both_stores_without_mutation(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-05-21.md"
    original = (
        "## 2026-05-21 10:00\n"
        "What happened:\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: agent-example\n"
    )
    day_file.write_text(original, encoding="utf-8")
    es_change = ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="doc-1",
        source={
            "entry_id": "agent-example",
            "source": "agent-session",
            "what_happened": "## Active Task\nFinished.",
        },
        updated_what_happened="### Active Task\nFinished.",
        entry_id="agent-example",
        headings_demoted=1,
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
    assert summary.markdown_headings_demoted == 1
    assert summary.elasticsearch_headings_demoted == 1
    assert summary.entry_ids == ("agent-example",)
    assert day_file.read_text(encoding="utf-8") == original
    assert client.updates == []
    assert not backup_root.exists()


def test_migration_apply_backs_up_and_updates_both_stores(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-05-21.md"
    original = (
        "## 2026-05-21 10:00\n"
        "What happened:\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: agent-example\n"
    )
    day_file.write_text(original, encoding="utf-8")
    es_change = ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="doc-1",
        source={
            "entry_id": "agent-example",
            "source": "agent-session",
            "what_happened": "## Active Task\nFinished.",
        },
        updated_what_happened="### Active Task\nFinished.",
        entry_id="agent-example",
        headings_demoted=1,
    )
    client = FakeElasticsearch([es_change])

    summary = run_migration(
        corpus,
        client,
        apply=True,
        backup_root=tmp_path / "backups",
    )

    assert summary.applied is True
    assert "### Active Task\n" in day_file.read_text(encoding="utf-8")
    assert client.updates == [((es_change,), False)]
    assert client.revalidations == [(es_change,)]
    assert summary.backup_dir is not None
    assert (summary.backup_dir / "markdown" / day_file.name).read_text(
        encoding="utf-8"
    ) == original
    es_backup = json.loads(
        (summary.backup_dir / "elasticsearch.json").read_text(encoding="utf-8")
    )
    assert es_backup[0]["_source"] == es_change.source
    manifest = json.loads(
        (summary.backup_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["markdown_files"] == 1
    assert manifest["elasticsearch_documents"] == 1


def test_elasticsearch_scan_limits_changes_to_agent_session_what_happened(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    response = {
        "hits": {
            "hits": [
                {
                    "_index": "harqis-hfl-entries",
                    "_id": "agent-doc",
                    "_source": {
                        "entry_id": "agent-example",
                        "source": "agent-session",
                        "what_happened": "## Active Task\nFinished.",
                    },
                },
                {
                    "_index": "harqis-hfl-entries",
                    "_id": "git-doc",
                    "_source": {
                        "entry_id": "git-example",
                        "source": "git",
                        "what_happened": "## Git heading\nFinished.",
                    },
                },
            ]
        }
    }
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: response)

    changes = client.scan("harqis-hfl-entries")

    assert len(changes) == 1
    assert changes[0].doc_id == "agent-doc"
    assert changes[0].updated_what_happened == "### Active Task\nFinished."
    assert changes[0].headings_demoted == 1


def test_elasticsearch_scan_recovers_truncated_historical_fence(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    response = {
        "hits": {
            "hits": [
                {
                    "_index": "harqis-hfl-entries",
                    "_id": "agent-doc",
                    "_seq_no": 3,
                    "_primary_term": 1,
                    "_source": {
                        "entry_id": "agent-example",
                        "source": "agent-session",
                        "what_happened": (
                            "```text\ntruncated\n"
                            "Why it stayed: historical fragment\n"
                            "## Active Task\nDone.\n"
                            "Source: agent-session\n"
                            "Entry ID: agent-example\n"
                        ),
                    },
                }
            ]
        }
    }
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: response)

    changes = client.scan("harqis-hfl-entries")

    assert len(changes) == 1
    assert "### Active Task\n" in changes[0].updated_what_happened


def test_elasticsearch_scan_recovers_truncated_fence_without_metadata(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    response = {
        "hits": {
            "hits": [
                {
                    "_index": "harqis-hfl-entries",
                    "_id": "agent-doc",
                    "_seq_no": 3,
                    "_primary_term": 1,
                    "_source": {
                        "entry_id": "agent-example",
                        "source": "agent-session",
                        "what_happened": "```text\ntruncated\n## Active Task\nDone.\n",
                    },
                }
            ]
        }
    }
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: response)

    changes = client.scan("harqis-hfl-entries")

    assert len(changes) == 1
    assert "### Active Task\n" in changes[0].updated_what_happened


def test_migration_rolls_back_when_elasticsearch_update_fails(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-05-21.md"
    original = (
        "## 2026-05-21 10:00\n"
        "What happened:\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: agent-example\n"
    )
    day_file.write_text(original, encoding="utf-8")
    es_change = ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="doc-1",
        source={
            "entry_id": "agent-example",
            "source": "agent-session",
            "what_happened": "## Active Task\nFinished.",
        },
        updated_what_happened="### Active Task\nFinished.",
        entry_id="agent-example",
        headings_demoted=1,
    )
    client = FakeElasticsearch([es_change], fail_updates=True)

    with pytest.raises(RuntimeError, match="update failed"):
        run_migration(
            corpus,
            client,
            apply=True,
            backup_root=tmp_path / "backups",
        )

    assert day_file.read_text(encoding="utf-8") == original
    assert client.updates[-1] == ((), True)


def test_elasticsearch_scan_scrolls_and_preserves_concurrency_tokens(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    requests = []
    pages = [
        {
            "_scroll_id": "scroll-1",
            "hits": {
                "hits": [
                    {
                        "_index": "harqis-hfl-entries",
                        "_id": "doc-1",
                        "_seq_no": 7,
                        "_primary_term": 2,
                        "_source": {
                            "entry_id": "entry-1",
                            "source": "agent-session",
                            "what_happened": "## Active Task\nDone.",
                        },
                    }
                ]
            },
        },
        {
            "_scroll_id": "scroll-2",
            "hits": {
                "hits": [
                    {
                        "_index": "harqis-hfl-entries",
                        "_id": "doc-2",
                        "_seq_no": 8,
                        "_primary_term": 3,
                        "_source": {
                            "entry_id": "entry-2",
                            "source": "agent-session",
                            "what_happened": "## Outcome\nDone.",
                        },
                    }
                ]
            },
        },
        {"_scroll_id": "scroll-2", "hits": {"hits": []}},
    ]

    def request(method, path, body=None, **kwargs):
        requests.append((method, path, body, kwargs))
        if method == "DELETE":
            return {}
        return pages.pop(0)

    monkeypatch.setattr(client, "_request", request)

    changes = client.scan("harqis-hfl-entries")

    assert [(change.doc_id, change.seq_no, change.primary_term) for change in changes] == [
        ("doc-1", 7, 2),
        ("doc-2", 8, 3),
    ]
    assert requests[0][2]["seq_no_primary_term"] is True
    assert [request[1] for request in requests].count("/_search/scroll") == 3


def test_elasticsearch_revalidation_rejects_concurrent_change(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    change = ElasticsearchChange(
        index="harqis-hfl-entries",
        doc_id="doc-1",
        source={"source": "agent-session", "what_happened": "## Active Task"},
        updated_what_happened="### Active Task",
        entry_id="entry-1",
        headings_demoted=1,
        seq_no=7,
        primary_term=2,
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
            "docs": [
                {
                    "found": True,
                    "_seq_no": 8,
                    "_primary_term": 2,
                    "_source": change.source,
                }
            ]
        },
    )

    with pytest.raises(RuntimeError, match="changed during migration preflight"):
        client.revalidate([change])


def test_elasticsearch_bulk_uses_occ_and_reports_only_confirmed_successes(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    changes = [
        ElasticsearchChange(
            index="harqis-hfl-entries",
            doc_id=f"doc-{number}",
            source={"source": "agent-session", "what_happened": "## Active Task"},
            updated_what_happened="### Active Task",
            entry_id=f"entry-{number}",
            headings_demoted=1,
            seq_no=number,
            primary_term=2,
        )
        for number in (7, 8)
    ]
    captured = {}

    def request(method, path, **kwargs):
        captured.update(kwargs)
        return {
            "errors": True,
            "items": [
                {"update": {"status": 200, "_seq_no": 9, "_primary_term": 2}},
                {"update": {"status": 409, "error": {"type": "version_conflict"}}},
            ],
        }

    monkeypatch.setattr(client, "_request", request)

    with pytest.raises(ElasticsearchBulkError) as error:
        client.update_what_happened(changes)

    assert [write.change.doc_id for write in error.value.successful_writes] == ["doc-7"]
    metadata = json.loads(captured["raw_body"].splitlines()[0])
    assert metadata["update"]["if_seq_no"] == 7
    assert metadata["update"]["if_primary_term"] == 2


def test_incomplete_bulk_response_retains_confirmed_successes(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    changes = [
        ElasticsearchChange(
            index="harqis-hfl-entries",
            doc_id=f"doc-{number}",
            source={"source": "agent-session", "what_happened": "## Active Task"},
            updated_what_happened="### Active Task",
            entry_id=f"entry-{number}",
            headings_demoted=1,
            seq_no=number,
            primary_term=1,
        )
        for number in (1, 2)
    ]
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
            "errors": False,
            "items": [{"update": {"status": 200, "_seq_no": 3, "_primary_term": 1}}],
        },
    )

    with pytest.raises(ElasticsearchBulkError) as error:
        client.update_what_happened(changes)

    assert [write.change.doc_id for write in error.value.successful_writes] == ["doc-1"]


def test_malformed_bulk_item_retains_earlier_confirmed_success(monkeypatch):
    client = ElasticsearchClient("http://localhost:9200")
    changes = [
        ElasticsearchChange(
            index="harqis-hfl-entries",
            doc_id=f"doc-{number}",
            source={"source": "agent-session", "what_happened": "## Active Task"},
            updated_what_happened="### Active Task",
            entry_id=f"entry-{number}",
            headings_demoted=1,
            seq_no=number,
            primary_term=1,
        )
        for number in (1, 2)
    ]
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {
            "errors": True,
            "items": [
                {"update": {"status": 200, "_seq_no": 3, "_primary_term": 1}},
                {"update": "malformed"},
            ],
        },
    )

    with pytest.raises(ElasticsearchBulkError) as error:
        client.update_what_happened(changes)

    assert [write.change.doc_id for write in error.value.successful_writes] == ["doc-1"]


def test_partial_es_success_rolls_back_only_success_and_surfaces_restore_failure(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    changes = [
        ElasticsearchChange(
            index="harqis-hfl-entries",
            doc_id=f"doc-{number}",
            source={"source": "agent-session", "what_happened": "## Active Task"},
            updated_what_happened="### Active Task",
            entry_id=f"entry-{number}",
            headings_demoted=1,
            seq_no=number,
            primary_term=1,
        )
        for number in (1, 2)
    ]

    class PartialClient(FakeElasticsearch):
        def update_what_happened(self, changes, *, restore=False):
            items = tuple(changes)
            self.updates.append((items, restore))
            if restore:
                raise RuntimeError("restore service unavailable")
            successful = ElasticsearchWrite(items[0], 3, 1)
            raise ElasticsearchBulkError("second item conflicted", [successful])

    client = PartialClient(changes)

    with pytest.raises(RuntimeError, match="ROLLBACK FAILURE.*Elasticsearch restoration"):
        run_migration(
            corpus,
            client,
            apply=True,
            backup_root=tmp_path / "backups",
        )

    restored_items, restore = client.updates[-1]
    assert restore is True
    assert [item.change.doc_id for item in restored_items] == ["doc-1"]


def test_multi_file_markdown_failure_restores_every_file(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    first_dir = corpus / "one"
    second_dir = corpus / "two"
    first_dir.mkdir(parents=True)
    second_dir.mkdir()
    original = (
        "## 2026-07-19 10:00\n"
        "## Active Task\n"
        "Source: agent-session\n"
        "Entry ID: entry\n"
    ).encode()
    files = [first_dir / "2026-07-19.md", second_dir / "2026-07-19.md"]
    for path in files:
        path.write_bytes(original)
    real_write = migration._write_relative
    updates = 0

    def fail_second_update(root_fd, relative, data, **kwargs):
        nonlocal updates
        if b"### Active Task" in data:
            updates += 1
            if updates == 2:
                raise OSError("simulated second-file write failure")
        return real_write(root_fd, relative, data, **kwargs)

    monkeypatch.setattr(migration, "_write_relative", fail_second_update)
    client = FakeElasticsearch()

    with pytest.raises(OSError, match="second-file"):
        run_migration(
            corpus,
            client,
            apply=True,
            backup_root=tmp_path / "backups",
        )

    assert [path.read_bytes() for path in files] == [original, original]
    assert client.updates[-1] == ((), True)


def test_apply_rejects_symlink_swap_without_touching_outside_file(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-07-19.md"
    outside = tmp_path / "outside.md"
    day_file.write_text(
        "## 2026-07-19 10:00\n## Active Task\nSource: agent-session\nEntry ID: entry\n",
        encoding="utf-8",
    )
    outside.write_bytes(b"outside must remain unchanged\n")

    class SwappingClient(FakeElasticsearch):
        def revalidate(self, changes):
            super().revalidate(changes)
            day_file.unlink()
            day_file.symlink_to(outside)

    with pytest.raises(OSError):
        run_migration(
            corpus,
            SwappingClient(),
            apply=True,
            backup_root=tmp_path / "backups",
        )

    assert outside.read_bytes() == b"outside must remain unchanged\n"


def test_regular_file_swap_is_rejected_without_clobbering_concurrent_content(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-07-19.md"
    day_file.write_text(
        "## 2026-07-19 10:00\n## Active Task\nSource: agent-session\nEntry ID: entry\n",
        encoding="utf-8",
    )

    class SwappingClient(FakeElasticsearch):
        def revalidate(self, changes):
            super().revalidate(changes)
            day_file.unlink()
            day_file.write_text("concurrent replacement\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="identity changed"):
        run_migration(
            corpus,
            SwappingClient(),
            apply=True,
            backup_root=tmp_path / "backups",
        )

    assert day_file.read_text(encoding="utf-8") == "concurrent replacement\n"


def test_in_place_change_during_replace_is_restored_and_rejected(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-07-19.md"
    original = b"## 2026-07-19 10:00\n## Active Task\nSource: agent-session\nEntry ID: entry\n"
    day_file.write_bytes(original)
    change = scan_markdown(corpus)[0]
    assert change.relative_path is not None
    root_fd = migration._open_root(corpus)
    real_replace = migration.os.replace
    injected = False

    def replace_with_concurrent_write(source, destination, **kwargs):
        nonlocal injected
        if not injected and ".tmp-" in source:
            injected = True
            day_file.write_bytes(b"concurrent owner data\n")
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(migration.os, "replace", replace_with_concurrent_write)
    try:
        with pytest.raises(RuntimeError, match="concurrent version restored"):
            migration._write_relative(
                root_fd,
                change.relative_path,
                change.updated_text.encode(),
                expected_identity=(change.device, change.inode),
                expected_bytes=change.original_bytes,
            )
    finally:
        migration.os.close(root_fd)

    assert day_file.read_bytes() == b"concurrent owner data\n"


def test_destination_inode_swap_after_replace_is_not_owned(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    day_file = corpus / "2026-07-19.md"
    original = b"## 2026-07-19 10:00\n## Active Task\nSource: agent-session\nEntry ID: entry\n"
    day_file.write_bytes(original)
    change = scan_markdown(corpus)[0]
    assert change.relative_path is not None
    updated_bytes = change.updated_text.encode()
    root_fd = migration._open_root(corpus)
    real_replace = migration.os.replace
    injected = False

    def replace_then_swap_destination(source, destination, **kwargs):
        nonlocal injected
        result = real_replace(source, destination, **kwargs)
        if not injected and ".tmp-" in source:
            injected = True
            concurrent = corpus / ".concurrent-owner"
            concurrent.write_bytes(updated_bytes)
            real_replace(concurrent, day_file)
        return result

    monkeypatch.setattr(migration.os, "replace", replace_then_swap_destination)
    try:
        with pytest.raises(RuntimeError, match="destination replaced concurrently"):
            migration._write_relative(
                root_fd,
                change.relative_path,
                updated_bytes,
                expected_identity=(change.device, change.inode),
                expected_bytes=change.original_bytes,
            )
    finally:
        migration.os.close(root_fd)

    assert day_file.read_bytes() == updated_bytes


def test_rollback_refuses_to_clobber_concurrent_owner_data(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    first_dir = corpus / "one"
    second_dir = corpus / "two"
    first_dir.mkdir(parents=True)
    second_dir.mkdir()
    original = b"## 2026-07-19 10:00\n## Active Task\nSource: agent-session\nEntry ID: entry\n"
    files = [first_dir / "2026-07-19.md", second_dir / "2026-07-19.md"]
    for path in files:
        path.write_bytes(original)
    real_write = migration._write_relative
    updates = 0

    def change_owner_then_fail(root_fd, relative, data, **kwargs):
        nonlocal updates
        if b"### Active Task" in data:
            updates += 1
            if updates == 2:
                raise OSError("second write failed")
        result = real_write(root_fd, relative, data, **kwargs)
        if updates == 1 and b"### Active Task" in data:
            files[0].write_bytes(b"concurrent owner data\n")
        return result

    monkeypatch.setattr(migration, "_write_relative", change_owner_then_fail)

    with pytest.raises(RuntimeError, match="ROLLBACK FAILURE"):
        run_migration(
            corpus,
            FakeElasticsearch(),
            apply=True,
            backup_root=tmp_path / "backups",
        )

    assert files[0].read_bytes() == b"concurrent owner data\n"


@pytest.mark.parametrize("name", [".locks", "backups"])
def test_apply_rejects_symlinked_lock_or_backup_tree(tmp_path, name):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "2026-07-19.md").write_text(
        "## 2026-07-19 10:00\n## Active Task\nSource: agent-session\nEntry ID: entry\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    target = corpus / ".locks" if name == ".locks" else tmp_path / "backups"
    target.symlink_to(outside, target_is_directory=True)

    with pytest.raises((OSError, ValueError)):
        run_migration(
            corpus,
            FakeElasticsearch(),
            apply=True,
            backup_root=tmp_path / "backups",
        )

    assert list(outside.iterdir()) == []


def test_duplicate_daily_basenames_have_unique_lock_paths():
    first = migration._lock_name(Path("2026/Jan/2026-01-01.md"))
    second = migration._lock_name(Path("archive/2026-01-01.md"))

    assert first != second
