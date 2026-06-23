"""Watchlist scan — offline, with retrieve() monkeypatched."""

from workflows.knowledge.tasks import topic_scan


def _hit(id_, source, text, distance, meta=None):
    return {"id": id_, "source": source, "ref": f"ref://{id_}",
            "text": text, "meta": meta or {}, "distance": distance}


def test_unknown_watchlist_lists_available(monkeypatch):
    out = topic_scan.topic_scan("does-not-exist")
    assert "error" in out
    assert isinstance(out["available"], list)


def test_scan_builds_cards_with_why(monkeypatch):
    hit = _hit("c1", "confluence",
               "Payments settlement uses an idempotency key. See PAY-1421.",
               0.3, meta={"title": "Settlement"})

    seen = {"n": 0}

    def fake_retrieve(query, k=5, source=None):
        # Same hit regardless of source; topic_scan de-dupes by id.
        seen["n"] += 1
        return [hit]

    monkeypatch.setattr(topic_scan, "retrieve", fake_retrieve)

    # 'payments-integration' ships in workflows/knowledge/watchlists.yaml
    out = topic_scan.topic_scan("payments-integration", k=5)
    assert out["count"] == 1
    card = out["cards"][0]
    assert card["source"] == "confluence"
    assert "settlement" in card["why"]["matched_keywords"]
    assert "Payments" in card["why"]["mentioned_services"]
    assert "PAY-1421" in card["why"]["jira_keys"]
    assert card["similarity"] > 0.9
