"""Deterministic entity extraction — pure, offline."""

from workflows.knowledge.entities import (
    extract_entities,
    entity_keys,
    shared_entities,
)

_VOCAB = ["Payments", "Ledger", "FraudCheck"]


def test_jira_keys_extracted():
    ents = extract_entities("Fixed in PAY-1421 and OPS-7; see also PAY-1421.")
    assert ents["jira_keys"] == ["PAY-1421", "OPS-7"]  # de-duped, order-stable


def test_pr_refs_qualified_and_bare():
    ents = extract_entities("Shipped acme/payments#42, follow-up in #1009.")
    assert "acme/payments#42" in ents["pr_refs"]
    assert "1009" in ents["pr_refs"]


def test_service_vocab_matches_whole_words_only():
    ents = extract_entities("The Payments service calls FraudCheck.", service_vocab=_VOCAB)
    assert set(ents["services"]) == {"Payments", "FraudCheck"}
    # 'Ledger' not mentioned → absent
    assert "Ledger" not in ents["services"]


def test_acronym_stopwords_filtered():
    ents = extract_entities("Use the API and the URL for SSO via RASP.")
    assert "API" not in ents["acronyms"]
    assert "URL" not in ents["acronyms"]
    assert "SSO" in ents["acronyms"]
    assert "RASP" in ents["acronyms"]


def test_shared_entities_namespaced():
    a = "Payments settlement is tracked in PAY-1421."
    b = "PAY-1421 touches the Payments and Ledger services."
    shared = shared_entities(a, b, service_vocab=_VOCAB)
    assert "jira:PAY-1421" in shared
    assert "svc:Payments" in shared
    # Ledger only appears in b → not shared
    assert "svc:Ledger" not in shared


def test_entity_keys_excludes_urls():
    ents = extract_entities("See https://example.com/x PAY-1.")
    keys = entity_keys(ents)
    assert "jira:PAY-1" in keys
    assert not any(k.startswith("url") for k in keys)
