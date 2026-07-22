"""Synchronous client for a canonical remote HFL corpus API."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import httpx

from config import get_settings
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    CorpusEntry,
    build_tree,
    paginate_documents,
    shallow_tree,
)
from services.safe_paths import ReferenceLink


class RemoteCorpusError(RuntimeError):
    """Raised when configured canonical corpus access is unavailable."""


def _entry(item: dict[str, Any]) -> CorpusEntry:
    return CorpusEntry(
        anchor=str(item["anchor"]),
        header=str(item.get("header") or ""),
        moment=str(item.get("moment") or ""),
        what_happened=str(item.get("what_happened") or ""),
        tags=tuple(str(tag) for tag in item.get("tags") or ()),
        text=str(item.get("text") or ""),
    )


def _document(payload: dict[str, Any]) -> CorpusDocument:
    tags = tuple(str(tag) for tag in payload.get("tags") or ())
    tag_counts = tuple(
        (str(item[0]), int(item[1]))
        for item in payload.get("tag_counts") or ()
    )
    entries = tuple(_entry(item) for item in payload.get("entries") or ())
    return CorpusDocument(
        relative_path=str(payload["relative_path"]),
        path=None,
        name=str(payload["name"]),
        text=str(payload.get("text") or ""),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        tags=tags,
        references=tuple(str(ref) for ref in payload.get("references") or ()),
        excerpt=str(payload.get("excerpt") or ""),
        tag_counts=tag_counts or tuple((tag, 1) for tag in tags[:10]),
        entry_count=int(payload.get("entry_count") or 0),
        entries=entries,
        matching_entry_count=(
            int(payload["matching_entry_count"])
            if payload.get("matching_entry_count") is not None
            else None
        ),
        tag_entry_anchors=tuple(
            (str(item[0]), str(item[1]))
            for item in payload.get("tag_entry_anchors") or ()
        ),
    )


def _tree(payload: dict[str, Any]) -> dict:
    return {
        "name": str(payload.get("name") or "Corpus"),
        "path": str(payload.get("path") or ""),
        "directories": [_tree(item) for item in payload.get("directories") or ()],
        "files": [_document(item) for item in payload.get("files") or ()],
    }


class RemoteCorpusClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 20.0):
        if not base_url.strip() or not token.strip():
            raise RemoteCorpusError(
                "Remote HFL corpus requires HFL_CORPUS_API_URL and HFL_CORPUS_API_TOKEN"
            )
        self.base_url = base_url.rstrip("/") + "/api/hfl"
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout = timeout

    @classmethod
    def from_settings(cls) -> "RemoteCorpusClient":
        settings = get_settings()
        return cls(settings.hfl_corpus_api_url, settings.hfl_corpus_api_token)

    def _get(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = httpx.get(
                self.base_url + path,
                headers=self.headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise RemoteCorpusError(f"Canonical HFL corpus unavailable: {exc}") from exc

    def index(self, *, params: dict[str, str]) -> dict[str, Any]:
        try:
            payload = self._get(
                "/documents", params={**params, "compact": "true"}
            ).json()
            documents = tuple(
                _document(item) for item in payload.get("documents") or ()
            )
            results = tuple(_document(item) for item in payload["results"])
            tree = (
                _tree(payload["tree"])
                if payload.get("tree") is not None
                else shallow_tree(build_tree(documents))
            )
            if payload.get("page") is None:
                result_page = paginate_documents(
                    results,
                    page=int(params.get("page") or 1),
                    page_size=int(params.get("page_size") or 20),
                )
                results = result_page.items
                page = result_page.page
                page_size = result_page.page_size
                total_pages = result_page.total_pages
                has_previous = result_page.has_previous
                has_next = result_page.has_next
            else:
                page = int(payload["page"])
                page_size = int(payload["page_size"])
                total_pages = int(payload["total_pages"])
                has_previous = bool(payload["has_previous"])
                has_next = bool(payload["has_next"])
            return {
                "documents": documents,
                "tree": tree,
                "results": results,
                "total_results": int(payload["total_results"]),
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "has_previous": has_previous,
                "has_next": has_next,
                "document_count": int(payload["document_count"]),
                "tag_cloud": [tuple(item) for item in payload.get("tag_cloud") or ()],
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError("Canonical HFL corpus returned an invalid index") from exc

    def tree(self, path: str = "") -> dict:
        try:
            payload = self._get("/tree", params={"path": path}).json()
            return _tree(payload["tree"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned an invalid directory tree"
            ) from exc

    def matches(
        self,
        relative_path: str,
        *,
        query: str,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        encoded = quote(relative_path.replace("\\", "/"), safe="/")
        try:
            payload = self._get(
                f"/matches/{encoded}",
                params={"q": query, "offset": offset, "limit": limit},
            ).json()
            return {
                "entries": tuple(_entry(item) for item in payload["entries"]),
                "total": int(payload["total"]),
                "offset": int(payload["offset"]),
                "limit": int(payload["limit"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned invalid matching entries"
            ) from exc

    def document(self, relative_path: str) -> tuple[CorpusDocument, list[ReferenceLink]]:
        encoded = quote(relative_path.replace("\\", "/"), safe="/")
        try:
            payload = self._get(f"/document/{encoded}").json()
            document = _document(payload["document"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError("Canonical HFL corpus returned an invalid document") from exc
        references = []
        for item in payload.get("references") or ():
            href = item.get("href")
            if item.get("kind") == "download" and item.get("token"):
                href = f"/hfl-corpus/remote-references/{item['token']}/download"
            references.append(ReferenceLink(
                label=str(item.get("label") or "reference"),
                kind=str(item.get("kind") or "blocked"),
                href=str(href) if href else None,
                reason=str(item.get("reason") or ""),
            ))
        return document, references

    def download(self, token: str) -> tuple[bytes, str, str]:
        response = self._get(f"/reference/{quote(token, safe='')}")
        disposition = response.headers.get("content-disposition", "")
        filename = "reference"
        marker = "filename*=utf-8''"
        marker_index = disposition.casefold().find(marker)
        if marker_index >= 0:
            filename = unquote(disposition[marker_index + len(marker):].strip())
        elif "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip().strip('"')
        return response.content, Path(filename).name, response.headers.get(
            "content-type", "application/octet-stream"
        )
