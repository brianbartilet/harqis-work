"""Local, snapshot-contained hybrid retrieval for corpus-share chat."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from config import get_settings
from modules.hfl_shares.models import ScopeSnapshot, SnapshotEntry
from modules.hfl_shares.store import ShareStore, get_share_store


_log = logging.getLogger(__name__)
_EMBED_LOCK = threading.RLock()
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "brian", "can", "could",
    "does", "for", "from", "have", "into", "latest", "most", "over", "show",
    "that", "the", "their", "there", "these", "this", "through", "what", "when",
    "where", "which", "with", "would", "your",
}
_TERM_EXPANSIONS = {
    "interview": {"career", "experience", "project", "skills", "work"},
    "places": {"location", "singapore", "travel", "trip", "visit"},
    "visited": {"location", "places", "travel", "trip"},
    "working": {"commit", "git", "project", "shipped", "work"},
    "work": {"commit", "git", "project", "shipped", "working"},
}


def _entry_hash(entry: SnapshotEntry) -> str:
    return hashlib.sha256(entry.text.encode("utf-8")).hexdigest()


def _terms(query: str) -> set[str]:
    terms = {
        token
        for token in _TOKEN.findall((query or "").casefold())
        if token not in _STOP_WORDS
    }
    expanded = set(terms)
    for term in terms:
        expanded.update(_TERM_EXPANSIONS.get(term, ()))
        if term.endswith("s") and len(term) > 4:
            expanded.add(term[:-1])
    return expanded


def _lexical_score(entry: SnapshotEntry, terms: set[str]) -> float:
    if not terms:
        return 0.0
    moment = entry.moment.casefold()
    source = entry.source.casefold()
    tags = {tag.casefold() for tag in entry.tags}
    text = entry.text.casefold()
    score = 0.0
    for term in terms:
        if term in tags:
            score += 10
        if term == source or term in source:
            score += 7
        if term in moment:
            score += 6
        score += min(4, text.count(term))
    return score


def lexical_entries(
    snapshot: ScopeSnapshot,
    query: str,
    *,
    k: int,
) -> tuple[SnapshotEntry, ...]:
    """Return the current deterministic lexical ranking, bounded to ``k``."""
    terms = _terms(query)
    if not terms:
        return snapshot.entries[:k]
    ranked = [
        (_lexical_score(entry, terms), index, entry)
        for index, entry in enumerate(snapshot.entries)
    ]
    if not any(item[0] for item in ranked):
        return snapshot.entries[:k]
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[2] for item in ranked[:k])


@lru_cache(maxsize=4)
def _embedding_model(model_name: str, cache_dir: str):
    """Load FastEmbed lazily so lexical fallback works without the package."""
    from fastembed import TextEmbedding

    return TextEmbedding(
        model_name=model_name,
        cache_dir=cache_dir,
    )


def _embed_documents(
    texts: Iterable[str],
    *,
    model_name: str,
    cache_dir: str,
) -> list[list[float]]:
    with _EMBED_LOCK:
        model = _embedding_model(model_name, cache_dir)
        return [
            [float(value) for value in vector]
            for vector in model.passage_embed(list(texts))
        ]


def _embed_query(
    query: str,
    *,
    model_name: str,
    cache_dir: str,
) -> list[float]:
    with _EMBED_LOCK:
        model = _embedding_model(model_name, cache_dir)
        vectors = list(model.query_embed(query))
    if len(vectors) != 1:
        raise RuntimeError("Local embedding model returned an invalid query vector.")
    return [float(value) for value in vectors[0]]


def _normalise(vector: Iterable[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in vector)
    magnitude = math.sqrt(sum(value * value for value in values))
    if not values or magnitude <= 0:
        raise ValueError("Local embedding model returned an empty vector.")
    return tuple(value / magnitude for value in values)


def _document_vectors(
    snapshot: ScopeSnapshot,
    *,
    share_id: str,
    model_name: str,
    cache_dir: str,
    store: ShareStore,
) -> dict[str, tuple[float, ...]]:
    hashes = {entry.id: _entry_hash(entry) for entry in snapshot.entries}
    cached = (
        store.get_share_embeddings(share_id, model_name=model_name)
        if share_id
        else {}
    )
    vectors: dict[str, tuple[float, ...]] = {
        entry.id: _normalise(cached[entry.id]["embedding"])
        for entry in snapshot.entries
        if entry.id in cached
        and cached[entry.id]["content_hash"] == hashes[entry.id]
    }
    missing = [entry for entry in snapshot.entries if entry.id not in vectors]
    if missing:
        generated = _embed_documents(
            (entry.text for entry in missing),
            model_name=model_name,
            cache_dir=cache_dir,
        )
        if len(generated) != len(missing):
            raise RuntimeError("Local embedding model returned an invalid batch.")
        new_rows = []
        for entry, vector in zip(missing, generated):
            normalised = _normalise(vector)
            vectors[entry.id] = normalised
            new_rows.append(
                {
                    "entry_id": entry.id,
                    "content_hash": hashes[entry.id],
                    "embedding": normalised,
                }
            )
        if share_id:
            store.upsert_share_embeddings(
                share_id,
                model_name=model_name,
                rows=new_rows,
            )
    return vectors


def retrieve_entries(
    snapshot: ScopeSnapshot,
    query: str,
    *,
    share_id: str = "",
    store: ShareStore | None = None,
) -> tuple[SnapshotEntry, ...]:
    """Hybrid-rank only entries contained in ``snapshot``.

    Any model, cache, or persistence failure falls back to the bounded lexical
    ranking. Corpus text and queries are embedded in-process; no embedding API
    is called.
    """
    settings = get_settings()
    k = max(1, min(20, int(settings.hfl_share_retrieval_k)))
    lexical = lexical_entries(snapshot, query, k=k)
    if not snapshot.entries:
        return ()
    try:
        model_name = settings.hfl_share_embedding_model.strip()
        if not model_name:
            raise RuntimeError("Local embedding model is not configured.")
        cache_dir = str(
            Path(settings.hfl_share_embedding_cache_dir).expanduser().resolve()
        )
        vector_store = store or get_share_store()
        document_vectors = _document_vectors(
            snapshot,
            share_id=share_id,
            model_name=model_name,
            cache_dir=cache_dir,
            store=vector_store,
        )
        query_vector = _normalise(
            _embed_query(
                query,
                model_name=model_name,
                cache_dir=cache_dir,
            )
        )
        terms = _terms(query)
        lexical_scores = {
            entry.id: _lexical_score(entry, terms) for entry in snapshot.entries
        }
        lexical_max = max(lexical_scores.values(), default=0.0) or 1.0
        semantic_weight = min(
            1.0,
            max(0.0, float(settings.hfl_share_semantic_weight)),
        )
        ranked = []
        for index, entry in enumerate(snapshot.entries):
            vector = document_vectors[entry.id]
            if len(vector) != len(query_vector):
                raise ValueError("Local embedding dimensions do not match.")
            semantic = sum(a * b for a, b in zip(query_vector, vector))
            lexical_score = lexical_scores[entry.id] / lexical_max
            combined = (
                semantic_weight * semantic
                + (1 - semantic_weight) * lexical_score
            )
            ranked.append((combined, index, entry))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in ranked[:k])
    except Exception as exc:  # noqa: BLE001 - lexical retrieval is the safe fallback
        _log.warning("local share retrieval unavailable: %s", type(exc).__name__)
        return lexical
