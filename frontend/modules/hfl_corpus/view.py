"""Cached, query-independent projections of the Activity Corpus."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from modules.hfl_corpus.corpus import (
    CorpusDocument,
    build_tree,
    common_sources,
    common_tags,
)
from modules.hfl_corpus.secrets import filter_documents


@dataclass(frozen=True)
class CorpusView:
    documents: tuple[CorpusDocument, ...]
    tag_cloud: tuple[tuple[str, int], ...]
    sources: tuple[str, ...]
    tree: dict


class CorpusViewCache:
    """Reuse expensive aggregates until ``CorpusIndex`` publishes a new tuple."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._raw_documents: tuple[CorpusDocument, ...] | None = None
        self._views: dict[tuple[bool, tuple[str, ...]], CorpusView] = {}

    def get(
        self,
        raw_documents: tuple[CorpusDocument, ...],
        *,
        include_secrets: bool,
        secret_tags: tuple[str, ...],
    ) -> CorpusView:
        key = (include_secrets, tuple(tag.casefold() for tag in secret_tags))
        with self._lock:
            if raw_documents is not self._raw_documents:
                self._raw_documents = raw_documents
                self._views.clear()
            cached = self._views.get(key)
            if cached is not None:
                return cached

            documents = (
                raw_documents
                if include_secrets
                else filter_documents(raw_documents, key[1])
            )
            view = CorpusView(
                documents=documents,
                tag_cloud=tuple(common_tags(raw_documents)),
                sources=tuple(common_sources(documents)),
                tree=build_tree(documents),
            )
            self._views[key] = view
            return view


corpus_view_cache = CorpusViewCache()
