"""Synchronous client for a canonical remote HFL corpus API."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote, unquote

import httpx
from starlette.datastructures import UploadFile

from config import get_settings
from modules.hfl_corpus.corpus import (
    CorpusDocument,
    CorpusEntry,
    build_tree,
    normalize_source,
    paginate_documents,
    shallow_tree,
    valid_source_filter_value,
)
from services.safe_paths import ReferenceLink


_client_lock = Lock()
_client: httpx.Client | None = None
_entity_document_cache = {}
_entity_cache_lock = Lock()


def _http_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=30.0,
                )
            )
        return _client


def close_remote_http_client() -> None:
    """Close the process-wide canonical corpus connection pool."""
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is not None:
        client.close()


def _discard_http_client(client: httpx.Client) -> None:
    global _client
    with _client_lock:
        if _client is client:
            _client = None
    client.close()


class RemoteCorpusError(RuntimeError):
    """Raised when configured canonical corpus access is unavailable."""


def _entry(item: dict[str, Any]) -> CorpusEntry:
    return CorpusEntry(
        anchor=str(item["anchor"]),
        header=str(item.get("header") or ""),
        moment=str(item.get("moment") or ""),
        what_happened=str(item.get("what_happened") or ""),
        tags=tuple(str(tag) for tag in item.get("tags") or ()),
        source=str(item.get("source") or ""),
        text=str(item.get("text") or ""),
        secret=bool(item.get("secret", False)),
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
    def knowledge_documents(self, month: str, *, secret_tags: tuple[str, ...] = ()):
        """Read one complete date scope, including entries without a source label."""
        import calendar
        params = {'include_secrets': 'false', 'secret_tags': ','.join(secret_tags),
                  'compact': 'false', 'date_field': 'entry', 'activity_from_year': '1900',
                  'include_entries': 'true',
                  # Older canonical APIs include entries for a nonempty query;
                  # whitespace has no search terms and preserves the full scope.
                  'q': ' '}
        if month == 'latest':
            index = self._get('/documents', params={**params, 'compact': 'true'}).json()
            counts = index.get('activity', {}).get('timeline_counts')
            if counts is None:
                raise RemoteCorpusError('Canonical API lacks complete activity date coverage')
            days = [day for day, count in counts.items() if int(count) > 0]
            month = max(days)[:7] if days else date.today().isoformat()[:7]
        if month != 'all':
            start = date.fromisoformat(month + '-01')
            end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
            params.update(date_from=start.isoformat(), date_to=end.isoformat())
        payload = self._get('/documents', params=params).json()
        listed = payload['results']
        if len(listed) != int(payload['total_results']):
            raise RemoteCorpusError('Canonical API returned an incomplete date scope')
        if all('entries' in item for item in listed):
            return tuple(_document(item) for item in listed), month
        # Revalidate the permitted manifest on every read. Reuse only unchanged,
        # identically scoped documents; never fall back to cached data on failure.
        import hashlib
        from concurrent.futures import ThreadPoolExecutor
        scope = (self.base_url, hashlib.sha256(self.headers['Authorization'].encode()).hexdigest(), secret_tags)
        def read(item):
            key = (scope, item['relative_path'])
            fingerprint = json.dumps(item, sort_keys=True)
            with _entity_cache_lock:
                cached = _entity_document_cache.get(key)
            if cached and cached[0] == fingerprint:
                return cached[1]
            document = self.document(item['relative_path'], secret_tags=secret_tags)[0]
            with _entity_cache_lock:
                _entity_document_cache[key] = (fingerprint, document)
                while len(_entity_document_cache) > 512:
                    _entity_document_cache.pop(next(iter(_entity_document_cache)))
            return document
        with ThreadPoolExecutor(max_workers=6) as pool:
            documents = tuple(pool.map(read, listed))
        return documents, month

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
        headers = {**self.headers, **kwargs.pop("headers", {})}
        client = _http_client()
        try:
            response = client.get(
                self.base_url + path,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.RemoteProtocolError:
            _discard_http_client(client)
            try:
                response = _http_client().get(
                    self.base_url + path,
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                raise RemoteCorpusError(
                    f"Canonical HFL corpus unavailable: {exc}"
                ) from exc
        except httpx.HTTPError as exc:
            raise RemoteCorpusError(f"Canonical HFL corpus unavailable: {exc}") from exc

    def _post(self, path: str, **kwargs) -> httpx.Response:
        try:
            timeout = kwargs.pop("timeout", self.timeout)
            response = _http_client().post(
                self.base_url + path,
                headers=self.headers,
                timeout=timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            try:
                detail = str(exc.response.json().get("detail") or "").strip()
            except (TypeError, ValueError):
                detail = ""
            message = detail or str(exc)
            raise RemoteCorpusError(
                f"Canonical HFL corpus rejected the entry: {message}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RemoteCorpusError(f"Canonical HFL corpus unavailable: {exc}") from exc

    @staticmethod
    def _create_result(result: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "entry_id": str(result["entry_id"]),
            "path": str(result["path"]),
            "duplicate": bool(result["duplicate"]),
            "indexed": bool(result["indexed"]),
            "delivery": str(result["delivery"]),
        }
        if "uploads" in result:
            payload["uploads"] = [str(path) for path in result["uploads"]]
        return payload

    def preview_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._post("/entries/preview", json=payload).json()
            return {
                "filename": str(result["filename"]),
                "markdown": str(result["markdown"]),
                "html": str(result["html"]),
                "payload": dict(result["payload"]),
                "enrichment": dict(result["enrichment"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned an invalid preview response"
            ) from exc

    def create_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._post("/entries", json=payload).json()
            return self._create_result(result)
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned an invalid create-entry response"
            ) from exc

    def create_entry_with_uploads(
        self,
        payload: dict[str, Any],
        uploads: list[UploadFile],
    ) -> dict[str, Any]:
        files = [
            (
                "files",
                (
                    upload.filename or "upload",
                    upload.file,
                    upload.content_type or "application/octet-stream",
                ),
            )
            for upload in uploads
        ]
        try:
            result = self._post(
                "/entries/upload",
                data={"payload": json.dumps(payload)},
                files=files,
                timeout=max(self.timeout, 300.0),
            ).json()
            return self._create_result(result)
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned an invalid upload response"
            ) from exc

    def index(self, *, params: dict[str, str]) -> dict[str, Any]:
        try:
            payload = self._get(
                "/documents", params={**params, "compact": "true"}
            ).json()
            if params.get("scope") and not payload.get("scope_supported"):
                raise RemoteCorpusError("Update the canonical corpus host to support combined views.")
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
            activity = payload.get("activity") or {}
            activity_year = int(
                activity.get("year")
                or params.get("activity_year")
                or datetime.now().year
            )
            sources = [
                str(source).strip()
                for source in payload.get("sources") or ()
                if valid_source_filter_value(str(source))
            ]
            requested_source = params.get("source", "")
            if "," in requested_source and normalize_source(
                str(payload.get("selected_source") or ""), sources
            ) != normalize_source(requested_source, sources):
                raise RemoteCorpusError(
                    "Canonical corpus does not support the selected sources. Update the corpus host and retry."
                )
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
                "sources": sources,
                "selected_source": normalize_source(
                    str(payload.get("selected_source") or ""), sources
                ),
                "activity": {
                    "year": activity_year,
                    "years": [
                        int(year)
                        for year in activity.get("years") or (datetime.now().year,)
                    ],
                    "counts": {
                        str(day): int(count)
                        for day, count in (activity.get("counts") or {}).items()
                    },
                    "documents": {
                        str(day): str(path)
                        for day, path in (activity.get("documents") or {}).items()
                    },
                },
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError("Canonical HFL corpus returned an invalid index") from exc

    def sharing_documents(
        self,
        sources: tuple[str, ...] | list[str],
        *,
        include_secrets: bool = False,
        secret_tags: tuple[str, ...] = (),
    ) -> tuple[CorpusDocument, ...]:
        """Load entry-bearing documents for an explicitly selected source scope."""
        documents: dict[str, CorpusDocument] = {}
        try:
            for source in dict.fromkeys(item.strip() for item in sources if item.strip()):
                payload = self._get(
                    "/documents",
                    params={
                        "source": source,
                        "compact": "false",
                        "page": "1",
                        "page_size": "20",
                        "include_secrets": str(include_secrets).lower(),
                        "secret_tags": ",".join(secret_tags),
                    },
                ).json()
                selected_source = str(payload.get("selected_source") or "")
                if selected_source.casefold() != source.casefold():
                    raise RemoteCorpusError(
                        f"Canonical HFL corpus source is unavailable: {source}"
                    )
                for item in payload.get("results") or ():
                    document = _document(item)
                    documents[document.relative_path] = document
        except RemoteCorpusError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned invalid sharing documents"
            ) from exc
        return tuple(
            sorted(
                documents.values(),
                key=lambda item: item.relative_path.casefold(),
            )
        )

    def tree(
        self,
        path: str = "",
        *,
        include_secrets: bool = False,
        secret_tags: tuple[str, ...] = (),
    ) -> dict:
        try:
            payload = self._get("/tree", params={
                "path": path,
                "include_secrets": str(include_secrets).lower(),
                "secret_tags": ",".join(secret_tags),
            }).json()
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
        source: str = "",
        scope: str = "",
        offset: int = 0,
        limit: int = 20,
        include_secrets: bool = False,
        secret_tags: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        encoded = quote(relative_path.replace("\\", "/"), safe="/")
        try:
            payload = self._get(
                f"/matches/{encoded}",
                params={
                    "q": query,
                    "source": source,
                    "scope": scope,
                    "offset": offset,
                    "limit": limit,
                    "include_secrets": str(include_secrets).lower(),
                    "secret_tags": ",".join(secret_tags),
                },
            ).json()
            if scope and not payload.get("scope_supported"):
                raise RemoteCorpusError("Update the corpus host to support combined view matches.")
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

    def day_matches(
        self,
        activity_day: date,
        *,
        query: str,
        source: str = "",
        scope: str = "",
        offset: int = 0,
        limit: int = 20,
        include_secrets: bool = False,
        secret_tags: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        try:
            payload = self._get(
                f"/day-matches/{activity_day.isoformat()}",
                params={
                    "q": query,
                    "source": source,
                    "scope": scope,
                    "offset": offset,
                    "limit": limit,
                    "include_secrets": str(include_secrets).lower(),
                    "secret_tags": ",".join(secret_tags),
                },
            ).json()
            if scope and not payload.get("scope_supported"):
                raise RemoteCorpusError("Update the corpus host to support combined view matches.")
            return {
                "matches": tuple(
                    (str(item["relative_path"]), _entry(item["entry"]))
                    for item in payload["matches"]
                ),
                "total": int(payload["total"]),
                "offset": int(payload["offset"]),
                "limit": int(payload["limit"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned invalid day matching entries"
            ) from exc

    def document(
        self,
        relative_path: str,
        *,
        include_secrets: bool = False,
        secret_tags: tuple[str, ...] = (),
    ) -> tuple[CorpusDocument, list[ReferenceLink]]:
        encoded = quote(relative_path.replace("\\", "/"), safe="/")
        try:
            payload = self._get(
                f"/document/{encoded}",
                params={
                    "include_secrets": str(include_secrets).lower(),
                    "secret_tags": ",".join(secret_tags),
                },
            ).json()
            document = _document(payload["document"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError("Canonical HFL corpus returned an invalid document") from exc
        references = []
        for item in payload.get("references") or ():
            href = item.get("href")
            preview_kind = str(item.get("preview_kind") or "")
            preview_url = ""
            media_url = ""
            thumbnail_url = ""
            if item.get("kind") == "download" and item.get("token"):
                base_url = f"/hfl-corpus/remote-references/{item['token']}"
                href = f"{base_url}/download"
                if preview_kind:
                    preview_url = f"{base_url}/preview"
                    media_url = f"{base_url}/media"
                    if preview_kind in {"image", "video"}:
                        thumbnail_url = f"{base_url}/thumbnail"
            references.append(ReferenceLink(
                label=str(item.get("label") or "reference"),
                kind=str(item.get("kind") or "blocked"),
                href=str(href) if href else None,
                reason=str(item.get("reason") or ""),
                source=str(item.get("source") or ""),
                preview_kind=preview_kind,
                preview_url=preview_url,
                media_url=media_url,
                thumbnail_url=thumbnail_url,
            ))
        return document, references

    def update_document(
        self,
        relative_path: str,
        text: str,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        encoded = quote(relative_path.replace("\\", "/"), safe="/")
        try:
            payload = self._post(
                f"/document/{encoded}",
                json={
                    "text": text,
                    "expected_updated_at": expected_updated_at,
                },
            ).json()
            return {
                "updated": bool(payload["updated"]),
                "relative_path": str(payload["relative_path"]),
                "size": int(payload["size"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RemoteCorpusError(
                "Canonical HFL corpus returned an invalid document update response"
            ) from exc

    def reference_content(
        self,
        token: str,
        endpoint: str,
        *,
        range_header: str = "",
    ) -> tuple[bytes, int, dict[str, str]]:
        headers = {"Range": range_header} if range_header else {}
        response = self._get(
            f"/reference/{quote(token, safe='')}/{endpoint}",
            headers=headers,
        )
        forwarded = {
            key: value
            for key, value in response.headers.items()
            if key.casefold() in {
                "accept-ranges",
                "cache-control",
                "content-length",
                "content-range",
                "content-type",
                "x-content-type-options",
            }
        }
        return response.content, response.status_code, forwarded

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
