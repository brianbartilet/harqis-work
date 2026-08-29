from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.web.services.core.decorators.deserializer import deserialized

from apps.hfl_corpus.references.dto.documents import DtoHflCorpusUpdateResult
from apps.hfl_corpus.references.web.base_api_service import BaseApiServiceHflCorpus


class ApiServiceHflCorpusDocuments(BaseApiServiceHflCorpus):
    """Search, retrieve, update, and download Activity Corpus documents."""

    @deserialized(dict)
    def list_documents(
        self,
        query: str = "",
        date_field: str = "created",
        date_from: str = "",
        date_to: str = "",
        sort: str = "desc",
        page: int = 1,
        page_size: int = 20,
        compact: bool = True,
        source: str = "",
        include_secrets: bool = False,
        secret_tags: str = "",
    ) -> dict:
        """Search and paginate corpus documents."""
        self.request.get().add_uri_parameter("documents").add_query_strings(
            q=query,
            date_field=date_field,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            page=page,
            page_size=page_size,
            compact=str(compact).lower(),
            source=source,
            include_secrets=str(include_secrets).lower(),
            secret_tags=secret_tags,
        )
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_tree(
        self,
        path: str = "",
        include_secrets: bool = False,
        secret_tags: str = "",
    ) -> dict:
        """Return a shallow tree for a corpus directory."""
        self.request.get().add_uri_parameter("tree").add_query_strings(
            path=path,
            include_secrets=str(include_secrets).lower(),
            secret_tags=secret_tags,
        )
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_matches(
        self,
        relative_path: str,
        query: str = "",
        source: str = "",
        offset: int = 0,
        limit: int = 20,
        include_secrets: bool = False,
        secret_tags: str = "",
    ) -> dict:
        """Return matching entries within one corpus document."""
        self.request.get() \
            .add_uri_parameter("matches") \
            .add_uri_parameter(relative_path) \
            .add_query_strings(
                q=query,
                source=source,
                offset=offset,
                limit=limit,
                include_secrets=str(include_secrets).lower(),
                secret_tags=secret_tags,
            )
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_document(
        self,
        relative_path: str,
        include_secrets: bool = False,
        secret_tags: str = "",
    ) -> dict:
        """Return one corpus document, its entries, and safe references."""
        self.request.get() \
            .add_uri_parameter("document") \
            .add_uri_parameter(relative_path) \
            .add_query_strings(
                include_secrets=str(include_secrets).lower(),
                secret_tags=secret_tags,
            )
        return self.client.execute_request(self.request.build())

    @deserialized(DtoHflCorpusUpdateResult)
    def update_document(
        self,
        relative_path: str,
        text: str,
        expected_updated_at: str | None = None,
    ) -> DtoHflCorpusUpdateResult:
        """Replace a corpus Markdown document after server-side validation."""
        self.request.post() \
            .add_uri_parameter("document") \
            .add_uri_parameter(relative_path) \
            .add_json_payload({
                "text": text,
                "expected_updated_at": expected_updated_at,
            })
        return self.client.execute_request(self.request.build())

    def get_reference_preview(self, token: str) -> dict:
        """Return a safe text/Markdown reference preview."""
        response = self._raw_request("GET", f"reference/{token}/preview")
        return {
            "content": response.text,
            "content_type": response.headers.get("content-type", ""),
            "status_code": response.status_code,
        }

    def download_reference(self, token: str, destination: str | Path) -> dict:
        """Download a referenced file to a caller-selected local path."""
        return self._download(f"reference/{token}", destination)

    def download_reference_media(self, token: str, destination: str | Path) -> dict:
        """Download inline image/video reference content to a local path."""
        return self._download(f"reference/{token}/media", destination)

    def download_reference_thumbnail(self, token: str, destination: str | Path) -> dict:
        """Download a generated media thumbnail to a local path."""
        return self._download(f"reference/{token}/thumbnail", destination)
