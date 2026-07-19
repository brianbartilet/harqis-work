"""Synchronous client for a canonical remote HFL corpus API."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import httpx

from config import get_settings
from modules.hfl_corpus.corpus import CorpusDocument
from services.safe_paths import ReferenceLink


class RemoteCorpusError(RuntimeError):
    """Raised when configured canonical corpus access is unavailable."""


def _document(payload: dict[str, Any]) -> CorpusDocument:
    return CorpusDocument(
        relative_path=str(payload["relative_path"]),
        path=None,
        name=str(payload["name"]),
        text=str(payload.get("text") or ""),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        tags=tuple(str(tag) for tag in payload.get("tags") or ()),
        references=tuple(str(ref) for ref in payload.get("references") or ()),
        excerpt=str(payload.get("excerpt") or ""),
    )


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
            payload = self._get("/documents", params=params).json()
            return {
                "documents": tuple(_document(item) for item in payload["documents"]),
                "results": tuple(_document(item) for item in payload["results"]),
                "total_results": int(payload["total_results"]),
                "document_count": int(payload["document_count"]),
                "tag_cloud": [tuple(item) for item in payload.get("tag_cloud") or ()],
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError("Canonical HFL corpus returned an invalid index") from exc

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
