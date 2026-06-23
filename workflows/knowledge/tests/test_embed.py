"""Shared embedder — batching, query path, provider dispatch (no network)."""

import pytest

from workflows.knowledge import embed


class _FakeEmbedder:
    def __init__(self):
        self.batch_calls = []
        self.single_calls = []

    def batch_embed_contents(self, texts, model, task_type):
        self.batch_calls.append((list(texts), model, task_type))
        return {"embeddings": [{"values": [float(len(t))]} for t in texts]}

    def embed_content(self, text, model, task_type):
        self.single_calls.append((text, model, task_type))
        return {"embedding": {"values": [float(len(text))]}}


@pytest.fixture
def fake(monkeypatch):
    f = _FakeEmbedder()
    monkeypatch.setattr(embed, "_gemini_embedder", lambda: f)
    monkeypatch.setenv("HARQIS_KNOWLEDGE_EMBED_PROVIDER", "gemini")
    return f


def test_embed_documents_batches(fake, monkeypatch):
    monkeypatch.setenv("HARQIS_KNOWLEDGE_EMBED_BATCH", "2")
    vecs = embed.embed_documents(["a", "bb", "ccc"])
    assert vecs == [[1.0], [2.0], [3.0]]
    assert len(fake.batch_calls) == 2          # 2 + 1
    assert fake.batch_calls[0][2] == "RETRIEVAL_DOCUMENT"


def test_embed_query_uses_query_task_type(fake):
    assert embed.embed_query("abcd") == [4.0]
    assert fake.single_calls[0][2] == "RETRIEVAL_QUERY"


def test_embed_documents_empty_is_noop(fake):
    assert embed.embed_documents([]) == []
    assert fake.batch_calls == []


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("HARQIS_KNOWLEDGE_EMBED_PROVIDER", "nope")
    with pytest.raises(RuntimeError):
        embed.embed_documents(["x"])
    with pytest.raises(RuntimeError):
        embed.embed_query("x")
