import logging
from dataclasses import asdict, is_dataclass
from typing import Optional

from mcp.server.fastmcp import FastMCP

from apps.hfl_corpus.config import CONFIG
from apps.hfl_corpus.references.web.api.documents import ApiServiceHflCorpusDocuments
from apps.hfl_corpus.references.web.api.entries import ApiServiceHflCorpusEntries

logger = logging.getLogger("harqis-mcp.hfl_corpus")


def _dict_result(result) -> dict:
    if isinstance(result, dict):
        return result
    if is_dataclass(result):
        return asdict(result)
    return result.__dict__ if hasattr(result, "__dict__") else {}


def register_hfl_corpus_tools(mcp: FastMCP):

    # --- Entries ---

    @mcp.tool()
    def create_hfl_corpus_entry(
        date: str,
        time: str,
        moment: str,
        what_happened: str,
        why_it_stayed: str = "",
        possible_use: str = "",
        source: str = "manual-entry",
        tags: str = "",
        references: str = "",
        include_location: bool = True,
        browser_latitude: Optional[float] = None,
        browser_longitude: Optional[float] = None,
        browser_location_status: str = "",
    ) -> dict:
        """Create a durable HFL entry. This writes Markdown and attempts an ES upsert.

        Args:
            date: Entry date in YYYY-MM-DD format.
            time: Local entry time in HH:MM or HH:MM:SS format.
            moment: Short description of the memorable moment.
            what_happened: Factual details of what happened.
            why_it_stayed: Why the moment remained notable.
            possible_use: How the memory might be useful later.
            source: Provenance label; defaults to manual-entry.
            tags: Space-separated tags, optionally prefixed with #.
            references: Newline-separated URLs or source paths.
            include_location: Whether server-side location enrichment is allowed.
            browser_latitude: Optional caller-supplied latitude.
            browser_longitude: Optional caller-supplied longitude.
            browser_location_status: Optional browser geolocation status label.
        """
        logger.info("Tool called: create_hfl_corpus_entry date=%s time=%s", date, time)
        result = ApiServiceHflCorpusEntries(CONFIG).create_entry(
            date, time, moment, what_happened, why_it_stayed, possible_use,
            source, tags, references, include_location,
            browser_latitude, browser_longitude, browser_location_status,
        )
        output = _dict_result(result)
        logger.info("create_hfl_corpus_entry done entry_id=%s", output.get("entry_id"))
        return output

    @mcp.tool()
    def preview_hfl_corpus_entry(
        date: str,
        time: str,
        moment: str,
        what_happened: str,
        why_it_stayed: str = "",
        possible_use: str = "",
        source: str = "manual-entry",
        tags: str = "",
        references: str = "",
        include_location: bool = False,
    ) -> dict:
        """Preview a rendered HFL entry without saving it.

        Args:
            date: Entry date in YYYY-MM-DD format.
            time: Local entry time in HH:MM or HH:MM:SS format.
            moment: Short description of the memorable moment.
            what_happened: Factual details of what happened.
            why_it_stayed: Why the moment remained notable.
            possible_use: How the memory might be useful later.
            source: Provenance label; defaults to manual-entry.
            tags: Space-separated tags, optionally prefixed with #.
            references: Newline-separated URLs or source paths.
            include_location: Whether server-side location enrichment is allowed.
        """
        logger.info("Tool called: preview_hfl_corpus_entry date=%s time=%s", date, time)
        result = ApiServiceHflCorpusEntries(CONFIG).preview_entry(
            date, time, moment, what_happened, why_it_stayed, possible_use,
            source, tags, references, include_location,
        )
        output = _dict_result(result)
        logger.info("preview_hfl_corpus_entry done")
        return output

    @mcp.tool()
    def upload_hfl_corpus_entry(
        date: str,
        time: str,
        moment: str,
        what_happened: str,
        file_paths: list[str],
        why_it_stayed: str = "",
        possible_use: str = "",
        source: str = "manual-entry",
        tags: str = "",
        references: str = "",
        include_location: bool = True,
    ) -> dict:
        """Create a durable HFL entry and upload attachments. This writes remote state.

        Args:
            date: Entry date in YYYY-MM-DD format.
            time: Local entry time in HH:MM or HH:MM:SS format.
            moment: Short description of the memorable moment.
            what_happened: Factual details of what happened.
            file_paths: Up to ten readable local attachment paths.
            why_it_stayed: Why the moment remained notable.
            possible_use: How the memory might be useful later.
            source: Provenance label; defaults to manual-entry.
            tags: Space-separated tags, optionally prefixed with #.
            references: Newline-separated URLs or source paths.
            include_location: Whether server-side location enrichment is allowed.
        """
        logger.info("Tool called: upload_hfl_corpus_entry files=%d", len(file_paths))
        result = ApiServiceHflCorpusEntries(CONFIG).create_entry_with_uploads(
            date, time, moment, what_happened, file_paths, why_it_stayed,
            possible_use, source, tags, references, include_location,
        )
        output = _dict_result(result)
        logger.info("upload_hfl_corpus_entry done entry_id=%s", output.get("entry_id"))
        return output

    # --- Documents ---

    @mcp.tool()
    def list_hfl_corpus_documents(
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
        """Search and paginate canonical HFL documents.

        Args:
            query: Text and/or #tag search query.
            date_field: Date basis, created or updated.
            date_from: Inclusive lower date bound in YYYY-MM-DD format.
            date_to: Inclusive upper date bound in YYYY-MM-DD format.
            sort: Result order, asc or desc.
            page: One-based page number.
            page_size: Number of documents per page.
            compact: Return the compact paginated representation.
            source: Optional entry-source filter.
            include_secrets: Include protected entries when authorized.
            secret_tags: Comma-separated tags treated as protected.
        """
        logger.info("Tool called: list_hfl_corpus_documents query=%s page=%s", query, page)
        result = ApiServiceHflCorpusDocuments(CONFIG).list_documents(
            query, date_field, date_from, date_to, sort, page, page_size,
            compact, source, include_secrets, secret_tags,
        )
        output = _dict_result(result)
        logger.info("list_hfl_corpus_documents done total=%s", output.get("total_results"))
        return output

    @mcp.tool()
    def get_hfl_corpus_tree(
        path: str = "",
        include_secrets: bool = False,
        secret_tags: str = "",
    ) -> dict:
        """Get a shallow directory tree from the canonical corpus.

        Args:
            path: Relative corpus directory; empty selects the root.
            include_secrets: Include protected entries when authorized.
            secret_tags: Comma-separated tags treated as protected.
        """
        logger.info("Tool called: get_hfl_corpus_tree path=%s", path)
        output = _dict_result(
            ApiServiceHflCorpusDocuments(CONFIG).get_tree(path, include_secrets, secret_tags)
        )
        logger.info("get_hfl_corpus_tree done")
        return output

    @mcp.tool()
    def list_hfl_corpus_matches(
        relative_path: str,
        query: str = "",
        source: str = "",
        offset: int = 0,
        limit: int = 20,
        include_secrets: bool = False,
        secret_tags: str = "",
    ) -> dict:
        """List matching entries within one HFL Markdown document.

        Args:
            relative_path: Corpus-relative Markdown document path.
            query: Text and/or #tag query.
            source: Optional entry-source filter.
            offset: Zero-based match offset.
            limit: Number of matches, capped at 20.
            include_secrets: Include protected entries when authorized.
            secret_tags: Comma-separated tags treated as protected.
        """
        logger.info("Tool called: list_hfl_corpus_matches path=%s", relative_path)
        result = ApiServiceHflCorpusDocuments(CONFIG).list_matches(
            relative_path, query, source, offset, limit, include_secrets, secret_tags
        )
        output = _dict_result(result)
        logger.info("list_hfl_corpus_matches done total=%s", output.get("total"))
        return output

    @mcp.tool()
    def get_hfl_corpus_document(
        relative_path: str,
        include_secrets: bool = False,
        secret_tags: str = "",
    ) -> dict:
        """Get one HFL document with parsed entries and safe references.

        Args:
            relative_path: Corpus-relative Markdown document path.
            include_secrets: Include protected entries when authorized.
            secret_tags: Comma-separated tags treated as protected.
        """
        logger.info("Tool called: get_hfl_corpus_document path=%s", relative_path)
        output = _dict_result(
            ApiServiceHflCorpusDocuments(CONFIG).get_document(
                relative_path, include_secrets, secret_tags
            )
        )
        logger.info("get_hfl_corpus_document done")
        return output

    @mcp.tool()
    def update_hfl_corpus_document(relative_path: str, text: str) -> dict:
        """Replace an HFL document. Destructive: overwrites canonical Markdown text.

        Args:
            relative_path: Corpus-relative Markdown document path.
            text: Complete replacement Markdown content.
        """
        logger.info("Tool called: update_hfl_corpus_document path=%s", relative_path)
        result = ApiServiceHflCorpusDocuments(CONFIG).update_document(relative_path, text)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_document done updated=%s", output.get("updated"))
        return output

    # --- References ---

    @mcp.tool()
    def get_hfl_corpus_reference_preview(token: str) -> dict:
        """Get a safe HTML preview for a text or Markdown reference.

        Args:
            token: Opaque reference token returned by get_hfl_corpus_document.
        """
        logger.info("Tool called: get_hfl_corpus_reference_preview token=%s", token)
        output = _dict_result(
            ApiServiceHflCorpusDocuments(CONFIG).get_reference_preview(token)
        )
        logger.info("get_hfl_corpus_reference_preview done")
        return output

    def _download(tool_name: str, method_name: str, token: str, destination: str) -> dict:
        logger.info("Tool called: %s token=%s destination=%s", tool_name, token, destination)
        service = ApiServiceHflCorpusDocuments(CONFIG)
        output = _dict_result(getattr(service, method_name)(token, destination))
        logger.info("%s done bytes=%s", tool_name, output.get("bytes_written"))
        return output

    @mcp.tool()
    def download_hfl_corpus_reference(token: str, destination: str) -> dict:
        """Download a reference to a local path. This writes a local file.

        Args:
            token: Opaque reference token returned by get_hfl_corpus_document.
            destination: Local output file path; parent directories are created.
        """
        return _download("download_hfl_corpus_reference", "download_reference", token, destination)

    @mcp.tool()
    def download_hfl_corpus_reference_media(token: str, destination: str) -> dict:
        """Download reference image/video content. This writes a local file.

        Args:
            token: Opaque reference token returned by get_hfl_corpus_document.
            destination: Local output file path; parent directories are created.
        """
        return _download(
            "download_hfl_corpus_reference_media", "download_reference_media", token, destination
        )

    @mcp.tool()
    def download_hfl_corpus_reference_thumbnail(token: str, destination: str) -> dict:
        """Download a reference thumbnail. This writes a local file.

        Args:
            token: Opaque reference token returned by get_hfl_corpus_document.
            destination: Local output file path; parent directories are created.
        """
        return _download(
            "download_hfl_corpus_reference_thumbnail",
            "download_reference_thumbnail",
            token,
            destination,
        )
