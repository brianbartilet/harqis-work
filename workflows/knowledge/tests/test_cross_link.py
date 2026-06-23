"""Cross-source linker — offline, with retrieve()/store monkeypatched."""

import pytest

from workflows.knowledge.tasks import cross_link


def _hit(id_, source, text, distance, meta=None):
    return {"id": id_, "source": source, "ref": f"ref://{id_}",
            "text": text, "meta": meta or {}, "distance": distance}


def test_similarity_bounds():
    assert cross_link._similarity(0.0) == pytest.approx(1.0)
    assert cross_link._similarity(2.0) == 0.0          # opposite vectors, clamped
    assert cross_link._similarity(2 ** 0.5) == pytest.approx(0.0, abs=1e-9)  # orthogonal


def test_relations_links_across_sources_on_shared_entity(monkeypatch):
    conf = _hit("c1", "confluence", "Payments settlement design. See PAY-1421.", 0.3)
    jira = _hit("j1", "jira", "PAY-1421: Payments settlement bug", 0.35)

    def fake_retrieve(query, k=5, source=None):
        if source == "confluence":
            return [conf]
        if source == "jira":
            return [jira]
        if source is None:
            return [conf, jira]
        return []

    monkeypatch.setattr(cross_link, "retrieve", fake_retrieve)

    out = cross_link.relations("Payments settlement", k=6)
    ids = {n["id"] for n in out["nodes"]}
    assert {"c1", "j1"} <= ids
    edges = out["edges"]
    assert any("jira:PAY-1421" in e["shared"] for e in edges)
    # edge crosses sources
    assert any({e["from_source"], e["to_source"]} == {"confluence", "jira"} for e in edges)
    # nodes are stripped of bulky text
    assert all("text" not in n for n in out["nodes"])


def test_orphan_jira_flags_low_doc_similarity(monkeypatch):
    rows = [{"id": "PAY-1421:0", "ref": "ref://PAY-1421",
             "meta": {"issue_key": "PAY-1421", "summary": "settlement bug"}}]
    monkeypatch.setattr(cross_link.store, "get_meta_by_source", lambda source: rows)
    # Best confluence match is far away (distance 1.2 → similarity ≈ 0.28).
    monkeypatch.setattr(cross_link, "retrieve",
                        lambda q, k=5, source=None: [_hit("c9", "confluence", "unrelated", 1.2)])

    out = cross_link.orphan_jira(min_doc_similarity=0.55, limit=10)
    assert out["orphan_count"] == 1
    assert out["orphans"][0]["issue_key"] == "PAY-1421"


def test_stale_docs_flags_doc_matching_merged_pr(monkeypatch):
    rows = [{"id": "123:0", "ref": "ref://page",
             "meta": {"page_id": "123", "title": "Payments settlement"}}]
    monkeypatch.setattr(cross_link.store, "get_meta_by_source", lambda source: rows)
    # Close code match (distance 0.6 → sim ≈ 0.82) that is already merged.
    code = _hit("acme/pay#42:0", "github", "settlement impl", 0.6,
                meta={"state": "closed", "merged": True, "kind": "pr"})
    monkeypatch.setattr(cross_link, "retrieve", lambda q, k=5, source=None: [code])

    out = cross_link.stale_docs(min_code_similarity=0.6, limit=10)
    assert out["candidate_count"] == 1
    assert out["candidates"][0]["page_id"] == "123"
    assert out["candidates"][0]["code_state"] == "closed"


def test_working_context_wires_signals_and_related(monkeypatch):
    signals = [{"when": "2026-06-22", "moment": "Debugged PAY-1421 settlement retry",
                "what_happened": "Payments webhook retries", "tags": [], "references": [],
                "source": "git"}]
    monkeypatch.setattr(cross_link, "_recent_signals", lambda since, limit: signals)
    monkeypatch.setattr(cross_link, "retrieve",
                        lambda q, k=5, source=None: [_hit("c1", "confluence",
                                                          "Payments settlement", 0.3)])

    out = cross_link.working_context(since="-3d", k=5, summarize=False)
    assert out["focus_signals"] == signals
    assert out["related"] and out["related"][0]["source"] == "confluence"
    assert "PAY-1421" in out["entities"]["jira_keys"]
