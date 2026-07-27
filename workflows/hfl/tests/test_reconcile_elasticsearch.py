from scripts.agents.hfl import reconcile_elasticsearch as reconcile


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
