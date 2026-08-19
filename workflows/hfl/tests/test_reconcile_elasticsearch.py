from datetime import datetime

from scripts.agents.hfl import reconcile_elasticsearch as reconcile
from workflows.hfl.dto import HflEntry


def _doc(moment: str) -> dict:
    return {
        "schema_version": 1,
        "source": "capture",
        "when": "2026-07-26T10:00:00",
        "entry_date": "2026-07-26",
        "moment": moment,
        "what_happened": "Kept",
        "why_it_stayed": "Useful",
        "possible_use": "Review",
        "tags": ["hfl"],
        "references": [],
        "machine": "harqis-server",
        "entry_id": "hfl-one",
        "synthesized": False,
        "indexed_at": "ignored",
    }


def test_compare_projection_distinguishes_missing_stale_and_unchanged():
    expected = {
        "hfl-missing": {**_doc("Missing"), "entry_id": "hfl-missing"},
        "hfl-stale": {**_doc("New"), "entry_id": "hfl-stale"},
        "hfl-same": {**_doc("Same"), "entry_id": "hfl-same"},
    }
    existing = {
        "hfl-stale": {**_doc("Old"), "entry_id": "hfl-stale"},
        "hfl-same": {
            **_doc("Same"),
            "entry_id": "hfl-same",
            "indexed_at": "different-but-ignored",
        },
    }

    result = reconcile.compare_projection(expected, existing)

    assert result.missing_ids == ("hfl-missing",)
    assert result.stale_ids == ("hfl-stale",)
    assert result.unchanged == 1


def test_scan_corpus_preserves_precise_time_and_explicit_synthesis(tmp_path):
    entry = HflEntry(
        when=datetime(2026, 7, 26, 19, 59, 33, 870000),
        moment="Desktop capture",
        source="desktop",
        machine="harqis-server",
        entry_id="hfl-precise",
        synthesized=True,
    )
    (tmp_path / "2026-07-26.md").write_text(entry.to_markdown(), encoding="utf-8")

    scan = reconcile.scan_corpus(tmp_path)
    document = scan.documents["hfl-precise"]

    assert document["when"] == "2026-07-26T19:59:33.870000"
    assert document["synthesized"] is True


def test_legacy_markdown_reconciliation_keeps_richer_existing_metadata(tmp_path):
    corpus = tmp_path / "hfl"
    corpus.mkdir()
    (corpus / "2026-07-26.md").write_text(
        HflEntry(
            when=datetime(2026, 7, 26, 19, 59),
            moment="Legacy minute entry",
            source="desktop",
            machine="windows-work-all",
            entry_id="hfl-legacy",
        ).to_markdown(),
        encoding="utf-8",
    )
    expected = reconcile.scan_corpus(corpus).documents
    existing = {
        "hfl-legacy": {
            **expected["hfl-legacy"],
            "when": "2026-07-26T19:59:33.870000",
            "synthesized": True,
        }
    }

    merged = reconcile.preserve_existing_legacy_metadata(expected, existing)

    assert merged["hfl-legacy"]["when"] == "2026-07-26T19:59:33.870000"
    assert merged["hfl-legacy"]["synthesized"] is True
    assert all(not key.startswith("_canonical_") for key in merged["hfl-legacy"])


def test_legacy_reconciliation_rejects_malformed_or_conflicting_live_time(tmp_path):
    entry = HflEntry(
        when=datetime(2026, 7, 26, 19, 59),
        moment="Legacy minute entry",
        source="desktop",
        machine="windows-work-all",
        entry_id="hfl-legacy",
    )
    (tmp_path / "2026-07-26.md").write_text(entry.to_markdown(), encoding="utf-8")
    expected = reconcile.scan_corpus(tmp_path).documents

    for value in ("not-a-date", "2026-07-26T20:00:33.870000"):
        existing = {"hfl-legacy": {**expected["hfl-legacy"], "when": value}}
        merged = reconcile.preserve_existing_legacy_metadata(expected, existing)
        assert merged["hfl-legacy"]["when"] == "2026-07-26T19:59:00"


def test_scan_corpus_skips_hidden_macos_sidecar_files(tmp_path):
    (tmp_path / "._2026-07-26.md").write_bytes(b"\x00\xffnot markdown")

    scan = reconcile.scan_corpus(tmp_path)

    assert scan.files == 0
    assert scan.documents == {}


def test_bulk_upsert_uses_deterministic_ids():
    calls = []

    class Client:
        def _request(self, method, path, body=None, **kwargs):
            calls.append((method, path, kwargs))
            return {"errors": False}

    reconcile.bulk_upsert(
        Client(),
        "harqis-hfl-entries-v2",
        {"hfl-one": _doc("One")},
        ("hfl-one",),
    )

    payload = calls[0][2]["raw_body"].decode("utf-8")
    assert '"_index": "harqis-hfl-entries-v2"' in payload
    assert '"_id": "hfl-one"' in payload


def test_fetch_and_upsert_resolve_meta_document_by_canonical_entry_id():
    calls = []

    class Client:
        def _request(self, method, path, body=None, **kwargs):
            calls.append((method, path, body, kwargs))
            if path.endswith("/_mget"):
                return {"docs": [{"_id": "hfl-one", "found": False}]}
            if path.endswith("/_search"):
                return {"hits": {"hits": [{
                    "_id": "meta-facebook-stable", "_source": _doc("Old")
                }]}}
            return {"errors": False}

    client = Client()
    existing = reconcile.fetch_existing(client, "harqis-hfl-entries", ["hfl-one"])
    assert existing["hfl-one"]["moment"] == "Old"
    assert existing.actual_ids["hfl-one"] == "meta-facebook-stable"

    reconcile.bulk_upsert(
        client, "harqis-hfl-entries", {"hfl-one": _doc("New")},
        ("hfl-one",), existing.actual_ids,
    )
    payload = calls[-1][3]["raw_body"].decode("utf-8")
    assert '"_id": "meta-facebook-stable"' in payload
