import logging
from dataclasses import asdict, is_dataclass
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from apps.hfl_corpus.config import CONFIG
from apps.hfl_corpus.references.web.api.documents import ApiServiceHflCorpusDocuments
from apps.hfl_corpus.references.web.api.entries import ApiServiceHflCorpusEntries
from apps.hfl_corpus.references.web.api.management import ApiServiceHflCorpusManagement

from apps.hfl_corpus.references.web.api.calendar import ApiServiceHflCorpusCalendar
from apps.hfl_corpus.references.web.api.entities import ApiServiceHflCorpusEntities
from apps.hfl_corpus.references.web.api.graph_views import ApiServiceHflCorpusGraphViews
from apps.hfl_corpus.references.web.api.ideas import ApiServiceHflCorpusIdeas
from apps.hfl_corpus.references.web.api.timeline import ApiServiceHflCorpusTimeline

logger = logging.getLogger("harqis-mcp.hfl_corpus")


def _dict_result(result) -> dict:
    if isinstance(result, dict):
        return result
    if is_dataclass(result):
        return asdict(result)
    return result.__dict__ if hasattr(result, "__dict__") else {}


def register_hfl_corpus_tools(mcp: FastMCP):

    # --- Actions, categories, and date pins ---

    def _management(method: str, **kwargs) -> dict:
        logger.info("Tool called: hfl_corpus %s", method)
        output = _dict_result(getattr(ApiServiceHflCorpusManagement(CONFIG), method)(**kwargs))
        logger.info("hfl_corpus %s done", method)
        return output

    @mcp.tool()
    def upload_hfl_corpus_attachments(resource: Literal['actions', 'pins'], source_id: str, file_paths: list[str]) -> dict:
        """Attach multiple supporting files to an action or pin (remote write).

        Args:
            resource: actions or pins.
            source_id: Existing action or pin ID.
            file_paths: Local file paths, 50 per task, 500 MB each, 25,000 MB total.
                Identical names/content are deduplicated on retry. Schedule only after upload succeeds.
        """
        return _management('upload_attachments', resource=resource, source_id=source_id, file_paths=file_paths)

    @mcp.tool()
    def list_hfl_corpus_attachments(resource: Literal['actions', 'pins'], source_id: str) -> dict:
        """List supporting files attached to a task.

        Args:
            resource: actions or pins.
            source_id: Existing action or pin ID.
        """
        return _management('list_attachments', resource=resource, source_id=source_id)

    @mcp.tool()
    def download_hfl_corpus_attachment(resource: Literal['actions', 'pins'], source_id: str, attachment_id: str, destination: str) -> dict:
        """Download an input attachment (writes a local file).

        Args:
            resource: actions or pins.
            source_id: Action or pin ID.
            attachment_id: ID returned by upload or list.
            destination: Local output file path.
        """
        return _management('download_attachment', resource=resource, source_id=source_id, attachment_id=attachment_id, destination=destination)

    @mcp.tool()
    def delete_hfl_corpus_attachment(resource: Literal['actions', 'pins'], source_id: str, attachment_id: str) -> dict:
        """Detach an input from future runs (remote write). Prior run files are retained.

        Args:
            resource: actions or pins.
            source_id: Action or pin ID.
            attachment_id: ID returned by upload or list.
        """
        return _management('delete_attachment', resource=resource, source_id=source_id, attachment_id=attachment_id)

    @mcp.tool()
    def create_hfl_corpus_action(
        request_id: str, title: str, expected_outcome: str = "",
        review_date: str = "", due_date: str = "", prompt: str = "",
        notes: str = "", source: Optional[dict] = None,
        matrix: str = "", matrix_confidence: str = "", matrix_reason: str = "",
    ) -> dict:
        """Create an action (writes remote state), with scheduled agent execution disabled.

        Args:
            request_id: Caller-generated UUID; reuse with identical fields on retry.
            title: Action title, at most 200 characters.
            expected_outcome: Optional outcome, at most 3,000 characters.
            review_date: YYYY-MM-DD or empty for no review date.
            due_date: YYYY-MM-DD or empty for no deadline.
            prompt: Optional Markdown instructions, at most 20,000 characters.
            notes: Optional notes, at most 6,000 characters.
            source: Optional object containing corpus-relative path and stable entry_id.
            matrix: Q1 urgent/important, Q2 important/not urgent, Q3 urgent/not important, Q4 neither; empty if unclassified.
            matrix_confidence: high, medium, low, or empty if unassessed.
            matrix_reason: Evidence-based classification rationale, at most 3,000 characters.
        """
        return _management("create_action", request_id=request_id, title=title,
                           expected_outcome=expected_outcome, review_date=review_date,
                           due_date=due_date, prompt=prompt, notes=notes, source=source,
                           matrix=matrix, matrix_confidence=matrix_confidence, matrix_reason=matrix_reason)

    @mcp.tool()
    def list_hfl_corpus_actions(closed: bool = False, offset: int = 0) -> dict:
        """List actions, up to 500 per page.

        Args:
            closed: True selects done/dismissed actions; false selects open states.
            offset: Nonnegative offset; advance until total is reached.
        """
        return _management("list_actions", closed=closed, offset=offset)

    @mcp.tool()
    def get_hfl_corpus_action(action_id: str) -> dict:
        """Read an action and its current version.

        Args:
            action_id: ID returned by create or list actions.
        """
        return _management("get_action", action_id=action_id)

    @mcp.tool()
    def update_hfl_corpus_action(action_id: str, version: int, changes: dict) -> dict:
        """Edit, complete, or dismiss an action (writes remote state).

        Args:
            action_id: ID returned by create or list actions.
            version: Latest version; a stale version returns 409. Read before retrying.
            changes: Fields to edit: title, expected_outcome, review_date, due_date,
                prompt, notes, status, completion_note, matrix, matrix_confidence, matrix_reason.
                Matrix: Q1/Q2/Q3/Q4; confidence: high/medium/low. Empty strings clear optional fields.
                Status: open, active, in_progress, incomplete, done, dismissed.
                Completion keeps the existing HFL receipt behavior. Cannot enable agents.
        """
        return _management("update_action", action_id=action_id, version=version, changes=changes)

    @mcp.tool()
    def get_hfl_corpus_action_history(action_id: str) -> dict:
        """Read immutable action revisions.

        Args:
            action_id: ID returned by create or list actions.
        """
        return _management("get_action_history", action_id=action_id)

    @mcp.tool()
    def create_hfl_corpus_category(name: str, color: str, instructions: str = "") -> dict:
        """Create a Memory Signal category (writes remote state).

        Args:
            name: Unique category name, 1–60 characters.
            color: Color from list_hfl_corpus_categories palette.
            instructions: Optional category guidance, at most 20,000 characters.
        """
        return _management("create_category", name=name, color=color, instructions=instructions)

    @mcp.tool()
    def list_hfl_corpus_categories() -> dict:
        """List active and archived Memory Signal categories and the color palette."""
        return _management("list_categories")

    @mcp.tool()
    def get_hfl_corpus_category(category_id: int) -> dict:
        """Read a Memory Signal category, including an archived category.

        Args:
            category_id: Numeric category ID returned by create or list.
        """
        return _management("get_category", category_id=category_id)

    @mcp.tool()
    def update_hfl_corpus_category(category_id: int, changes: dict) -> dict:
        """Edit a category (writes remote state).

        Args:
            category_id: Numeric category ID returned by create or list.
            changes: Fields to edit: name, color, instructions. Omitted fields are preserved.
        """
        return _management("update_category", category_id=category_id, changes=changes)

    @mcp.tool()
    def archive_hfl_corpus_category(category_id: int) -> dict:
        """Archive a category and hide its pins, retaining history (writes remote state).

        Args:
            category_id: Numeric category ID returned by create or list.
        """
        return _management("archive_category", category_id=category_id)

    @mcp.tool()
    def create_hfl_corpus_pin(category_id: int, start_date: str, end_date: str,
                              title: str, note: str = "", prompt: str = "") -> dict:
        """Pin dates (writes remote state). A prompt does not enable agent execution.

        Args:
            category_id: Active Memory Signal category ID.
            start_date: YYYY-MM-DD, no earlier than the profile birthdate.
            end_date: Inclusive YYYY-MM-DD, at most five years ahead. Same date pins one day.
            title: Required title, at most 2,000 characters.
            note: Optional note, at most 2,000 characters.
            prompt: Optional Markdown instructions, at most 20,000 characters.
        """
        return _management("create_pin", category_id=category_id, start_date=start_date,
                           end_date=end_date, title=title, note=note, prompt=prompt)

    @mcp.tool()
    def list_hfl_corpus_pins(category_id: Optional[int] = None) -> dict:
        """List date pins in active categories.

        Args:
            category_id: Optional category filter.
        """
        return _management("list_pins", category_id=category_id)

    @mcp.tool()
    def get_hfl_corpus_pin(pin_id: int) -> dict:
        """Read a date pin in an active category.

        Args:
            pin_id: Numeric pin ID returned by create or list.
        """
        return _management("get_pin", pin_id=pin_id)

    @mcp.tool()
    def update_hfl_corpus_pin(pin_id: int, changes: dict) -> dict:
        """Edit a date pin (writes remote state); preserves its agent setting.

        Args:
            pin_id: Numeric pin ID returned by create or list.
            changes: Fields to edit: category_id, start_date, end_date, title, note, prompt.
                Dates use YYYY-MM-DD. Omitted fields are preserved.
        """
        return _management("update_pin", pin_id=pin_id, changes=changes)

    @mcp.tool()
    def delete_hfl_corpus_pin(pin_id: int) -> dict:
        """Delete a date pin (destructive remote write).

        Args:
            pin_id: Numeric pin ID returned by create or list.
        """
        return _management("delete_pin", pin_id=pin_id)

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
        include_entries: bool = False,
        activity_year: int = 0,
        activity_from_year: int = 0,
        scope: dict | None = None,
    ) -> dict:
        """Search and paginate canonical HFL documents.

        Args:
            query: Text and/or #tag search query.
            date_field: Date basis: created, updated, or entry.
            date_from: Inclusive lower date bound in YYYY-MM-DD format.
            date_to: Inclusive upper date bound in YYYY-MM-DD format.
            sort: Result order, asc or desc.
            page: One-based page number.
            page_size: Number of documents per page.
            compact: Return the compact paginated representation.
            source: Optional entry-source filter.
            include_secrets: Include protected entries when authorized.
            secret_tags: Comma-separated tags treated as protected.
            include_entries: Include entry payloads in the document response.
            activity_year: Calendar year to include; zero uses the server default.
            activity_from_year: Earliest calendar year to include; zero uses the server default.
            scope: Optional combined-view object containing any/all filter clauses.
        """
        logger.info("Tool called: list_hfl_corpus_documents query=%s page=%s", query, page)
        result = ApiServiceHflCorpusDocuments(CONFIG).list_documents(
            query, date_field, date_from, date_to, sort, page, page_size,
            compact, source, include_secrets, secret_tags,
            include_entries, activity_year, activity_from_year, scope,
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
        scope: dict | None = None,
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
            scope: Optional combined-view object containing any/all filter clauses.
        """
        logger.info("Tool called: list_hfl_corpus_matches path=%s", relative_path)
        result = ApiServiceHflCorpusDocuments(CONFIG).list_matches(
            relative_path, query, source, offset, limit, include_secrets, secret_tags, scope
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
    def update_hfl_corpus_document(relative_path: str, text: str, expected_updated_at: str | None = None) -> dict:
        """Replace an HFL document. Destructive: overwrites canonical Markdown text.

        Args:
            relative_path: Corpus-relative Markdown document path.
            text: Complete replacement Markdown content.
            expected_updated_at: Last-read document timestamp; stale updates return 409. None preserves legacy unconditional behavior.
        """
        logger.info("Tool called: update_hfl_corpus_document path=%s", relative_path)
        result = ApiServiceHflCorpusDocuments(CONFIG).update_document(relative_path, text, expected_updated_at)
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

    # --- Canonical frontend operations (also exposed through the shared CLI) ---

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_entities(
        query: str = '',
        kind: str = '',
        offset: int = 0,
        limit: int = 100,
        source: str = '',
        since: str = '',
        until: str = '',
        context: str = '',
        graph_query: str = '',
        sources: list[str] | None = None,
    ) -> dict:
        """Search the entity directory with explicit pagination (limit 1–10000).

        Args:
            query: Search text; empty means no text filter.
            kind: Kind.
            offset: Nonnegative pagination offset.
            limit: Maximum results; subject to server limits.
            source: Source.
            since: Lower date filter, YYYY-MM-DD or empty.
            until: Upper date filter, YYYY-MM-DD or empty.
            context: Context.
            graph_query: Graph query.
            sources: Repeated source filters; None omits the filter.
        """
        logger.info("Tool called: list_hfl_corpus_entities")
        result = ApiServiceHflCorpusEntities(CONFIG).list_entities(query=query, kind=kind, offset=offset, limit=limit, source=source, since=since, until=until, context=context, graph_query=graph_query, sources=sources)
        output = _dict_result(result)
        logger.info("list_hfl_corpus_entities done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_entity_graph(
        query: str = '',
        limit: int = 100,
        source: str = '',
        since: str = '',
        until: str = '',
        shared: bool = False,
        sources: list[str] | None = None,
        context: str = '',
    ) -> dict:
        """Read the entity graph; limit is 0–1000, with 0 requesting all nodes.

        Args:
            query: Search text; empty means no text filter.
            limit: Maximum results; subject to server limits.
            source: Source.
            since: Lower date filter, YYYY-MM-DD or empty.
            until: Upper date filter, YYYY-MM-DD or empty.
            shared: Shared.
            sources: Repeated source filters; None omits the filter.
            context: Context.
        """
        logger.info("Tool called: get_hfl_corpus_entity_graph")
        result = ApiServiceHflCorpusEntities(CONFIG).get_entity_graph(query=query, limit=limit, source=source, since=since, until=until, shared=shared, sources=sources, context=context)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_entity_graph done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_entity_entry(entry_id: str, locator: str = '') -> dict:
        """Read an entity-linked entry preview and its safe references.

        Args:
            entry_id: Stable HFL entry ID.
            locator: Locator.
        """
        logger.info("Tool called: get_hfl_corpus_entity_entry")
        result = ApiServiceHflCorpusEntities(CONFIG).get_entity_entry(entry_id=entry_id, locator=locator)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_entity_entry done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_entity_status() -> dict:
        """Read entity enrichment state and legacy merge decisions.
        """
        logger.info("Tool called: get_hfl_corpus_entity_status")
        result = ApiServiceHflCorpusEntities(CONFIG).get_entity_status()
        output = _dict_result(result)
        logger.info("get_hfl_corpus_entity_status done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_entity_profile(
        identity: str,
        name: str,
        categories: list[str] | None = None,
        emails: list[str] | None = None,
        phones: list[str] | None = None,
        references: list[str] | None = None,
        notes: str = '',
    ) -> dict:
        """Replace entity profile fields; omitted lists are cleared. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            name: Name.
            categories: Categories.
            emails: Emails.
            phones: Phones.
            references: References.
            notes: Notes.
        """
        logger.info("Tool called: update_hfl_corpus_entity_profile")
        result = ApiServiceHflCorpusEntities(CONFIG).update_entity_profile(identity=identity, name=name, categories=categories, emails=emails, phones=phones, references=references, notes=notes)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_entity_profile done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity_backfill(include_new_types: bool = False) -> dict:
        """Request entity enrichment/backfill on the canonical host. Destructive: writes remote state.
        """
        logger.info("Tool called: create_hfl_corpus_entity_backfill")
        result = ApiServiceHflCorpusEntities(CONFIG).create_entity_backfill(include_new_types=include_new_types)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_entity_backfill done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity_legacy_merge(alias: str, canonical: str, reason: str) -> dict:
        """Legacy pair merge; prefer the preview-token bulk merge flow. Destructive: writes remote state.

        Args:
            alias: Alias.
            canonical: Canonical.
            reason: Evidence explaining the merge, 5–1000 characters.
        """
        logger.info("Tool called: create_hfl_corpus_entity_legacy_merge")
        result = ApiServiceHflCorpusEntities(CONFIG).create_entity_legacy_merge(alias=alias, canonical=canonical, reason=reason)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_entity_legacy_merge done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_entity_legacy_undo(decision_id: int) -> dict:
        """Undo a legacy pair-merge decision. Destructive: writes remote state.

        Args:
            decision_id: Decision id.
        """
        logger.info("Tool called: update_hfl_corpus_entity_legacy_undo")
        result = ApiServiceHflCorpusEntities(CONFIG).update_entity_legacy_undo(decision_id=decision_id)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_entity_legacy_undo done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity_export() -> dict:
        """Write the canonical host’s configured Obsidian export; requires HARQIS_OBSIDIAN_VAULT. Destructive: writes remote state.
        """
        logger.info("Tool called: create_hfl_corpus_entity_export")
        result = ApiServiceHflCorpusEntities(CONFIG).create_entity_export()
        output = _dict_result(result)
        logger.info("create_hfl_corpus_entity_export done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def analyze_hfl_corpus_entity_selection(entity_ids: list[str], name: str, evidence: str = '') -> dict:
        """Preview a same-type entity merge and obtain a short-lived preview token. Read-only.

        Args:
            entity_ids: Entity ids.
            name: Name.
            evidence: Evidence.
        """
        logger.info("Tool called: analyze_hfl_corpus_entity_selection")
        result = ApiServiceHflCorpusEntities(CONFIG).analyze_entity_selection(entity_ids=entity_ids, name=name, evidence=evidence)
        output = _dict_result(result)
        logger.info("analyze_hfl_corpus_entity_selection done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity_merge(
        entity_ids: list[str],
        name: str,
        request_id: str,
        preview_token: str,
        evidence: str = '',
        profile: dict | None = None,
    ) -> dict:
        """Commit a reviewed entity merge; reuse the UUID and identical payload on retry. Destructive: writes remote state.

        Args:
            entity_ids: Entity ids.
            name: Name.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            preview_token: Token returned by analyze_hfl_corpus_entity_selection; expires after 15 minutes.
            evidence: Evidence.
            profile: Optional overrides: categories, emails, phones, references, notes; omitted keys are preserved.
        """
        logger.info("Tool called: create_hfl_corpus_entity_merge")
        result = ApiServiceHflCorpusEntities(CONFIG).create_entity_merge(entity_ids=entity_ids, name=name, request_id=request_id, preview_token=preview_token, evidence=evidence, profile=profile)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_entity_merge done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_entity_unmerge(identity: str, request_id: str, evidence: str = '') -> dict:
        """Reverse a bulk merge, preserving audit history; UUID is required for idempotency. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            evidence: Evidence.
        """
        logger.info("Tool called: update_hfl_corpus_entity_unmerge")
        result = ApiServiceHflCorpusEntities(CONFIG).update_entity_unmerge(identity=identity, request_id=request_id, evidence=evidence)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_entity_unmerge done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_entity_operation(request_id: str) -> dict:
        """Read a committed merge/unmerge result and audit delivery state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
        """
        logger.info("Tool called: get_hfl_corpus_entity_operation")
        result = ApiServiceHflCorpusEntities(CONFIG).get_entity_operation(request_id=request_id)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_entity_operation done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_entity_audit(identity: str) -> dict:
        """Read immutable entity merge/unmerge audit events.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_entity_audit")
        result = ApiServiceHflCorpusEntities(CONFIG).get_entity_audit(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_entity_audit done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_entity_matching(all: bool = False) -> dict:
        """Read matching scan status and candidate suggestions.
        """
        logger.info("Tool called: get_hfl_corpus_entity_matching")
        result = ApiServiceHflCorpusEntities(CONFIG).get_entity_matching(all=all)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_entity_matching done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity_matching_scan() -> dict:
        """Request a matching scan; this may schedule background work. Destructive: writes remote state.
        """
        logger.info("Tool called: create_hfl_corpus_entity_matching_scan")
        result = ApiServiceHflCorpusEntities(CONFIG).create_entity_matching_scan()
        output = _dict_result(result)
        logger.info("create_hfl_corpus_entity_matching_scan done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_entity_matching_dismiss(identity: str) -> dict:
        """Dismiss a matching suggestion. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: update_hfl_corpus_entity_matching_dismiss")
        result = ApiServiceHflCorpusEntities(CONFIG).update_entity_matching_dismiss(identity=identity)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_entity_matching_dismiss done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_graph_views() -> dict:
        """List saved graph views and the selected view.
        """
        logger.info("Tool called: list_hfl_corpus_graph_views")
        result = ApiServiceHflCorpusGraphViews(CONFIG).list_graph_views()
        output = _dict_result(result)
        logger.info("list_hfl_corpus_graph_views done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_graph_view(name: str, state: dict) -> dict:
        """Create and select a named graph view. Destructive: writes remote state.

        Args:
            name: Name.
            state: View state: density, query, sources, since/until, rolling, shared, group, enabled, focus, layout. Server validates fields.
        """
        logger.info("Tool called: create_hfl_corpus_graph_view")
        result = ApiServiceHflCorpusGraphViews(CONFIG).create_graph_view(name=name, state=state)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_graph_view done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_graph_view(identity: str, name: str, state: dict, revision: int) -> dict:
        """Replace a saved graph view using its latest revision. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            name: Name.
            state: Complete graph view state, including layout if it must be retained.
            revision: Latest saved-view revision; stale writes return 409.
        """
        logger.info("Tool called: update_hfl_corpus_graph_view")
        result = ApiServiceHflCorpusGraphViews(CONFIG).update_graph_view(identity=identity, name=name, state=state, revision=revision)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_graph_view done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_graph_view_selection(identity: str) -> dict:
        """Select an existing saved graph view. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: update_hfl_corpus_graph_view_selection")
        result = ApiServiceHflCorpusGraphViews(CONFIG).update_graph_view_selection(identity=identity)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_graph_view_selection done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def delete_hfl_corpus_graph_view(identity: str, revision: int) -> dict:
        """Delete a graph view with an optimistic revision check. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            revision: Latest saved-view revision; stale writes return 409.
        """
        logger.info("Tool called: delete_hfl_corpus_graph_view")
        result = ApiServiceHflCorpusGraphViews(CONFIG).delete_graph_view(identity=identity, revision=revision)
        output = _dict_result(result)
        logger.info("delete_hfl_corpus_graph_view done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_timeline_source(path: str, entry_id: str) -> dict:
        """Validate and read the title/date of unprotected entry evidence.

        Args:
            path: Corpus-relative Markdown document path.
            entry_id: Stable HFL entry ID.
        """
        logger.info("Tool called: get_hfl_corpus_timeline_source")
        result = ApiServiceHflCorpusTimeline(CONFIG).get_timeline_source(path=path, entry_id=entry_id)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_timeline_source done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_timeline_evidence(path: str, entry_id: str) -> dict:
        """Return the validated evidence navigation link without following its redirect.

        Args:
            path: Corpus-relative Markdown document path.
            entry_id: Stable HFL entry ID.
        """
        logger.info("Tool called: get_hfl_corpus_timeline_evidence")
        result = ApiServiceHflCorpusTimeline(CONFIG).get_timeline_evidence(path=path, entry_id=entry_id)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_timeline_evidence done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_timeline_items(
        closed: bool = False,
        offset: int = 0,
        include_closed: bool = False,
        recent_dismissed: bool = False,
        query: str = '',
        source: str = '',
        date_field: str = 'created',
        date_from: str = '',
        date_to: str = '',
        rolling: int = 0,
        scope: dict | None = None,
    ) -> dict:
        """List up to 500 scoped agenda items with board positions and due-state grouping.

        Args:
            closed: Closed.
            offset: Nonnegative pagination offset.
            include_closed: Include closed.
            recent_dismissed: Recent dismissed.
            query: Search text; empty means no text filter.
            source: Source.
            date_field: Date field.
            date_from: Date from.
            date_to: Date to.
            rolling: Rolling.
            scope: Optional combined-view object with any/all filter clauses.
        """
        logger.info("Tool called: list_hfl_corpus_timeline_items")
        result = ApiServiceHflCorpusTimeline(CONFIG).list_timeline_items(closed=closed, offset=offset, include_closed=include_closed, recent_dismissed=recent_dismissed, query=query, source=source, date_field=date_field, date_from=date_from, date_to=date_to, rolling=rolling, scope=scope)
        output = _dict_result(result)
        logger.info("list_hfl_corpus_timeline_items done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_timeline_order(status: str, items: list[dict]) -> dict:
        """Reorder a status column with item version checks. Destructive: writes remote state.

        Args:
            status: Status.
            items: Ordered objects containing id and version; use the latest versions.
        """
        logger.info("Tool called: update_hfl_corpus_timeline_order")
        result = ApiServiceHflCorpusTimeline(CONFIG).update_timeline_order(status=status, items=items)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_timeline_order done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_timeline_item(item: dict) -> dict:
        """Create/adopt an agenda item. May configure agent execution if explicitly requested. Destructive: writes remote state.

        Args:
            item: Action fields: request_id UUID, title, expected_outcome, source, suggestion_id, review_date, due_date, prompt, notes, checklists, matrix, agent_enabled. Server validates; omission preserves normal defaults.
        """
        logger.info("Tool called: create_hfl_corpus_timeline_item")
        result = ApiServiceHflCorpusTimeline(CONFIG).create_timeline_item(item=item)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_timeline_item done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_timeline_item(followup_id: str, version: int, changes: dict) -> dict:
        """Update an agenda item using its latest version. Can alter scheduling; completion writes a receipt. Destructive: writes remote state.

        Args:
            followup_id: Followup id.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Action fields to change; status, dates, title, expected_outcome, prompt, notes, checklists, matrix, agent_enabled. Do not supply internal _agent_actor attribution.
        """
        logger.info("Tool called: update_hfl_corpus_timeline_item")
        result = ApiServiceHflCorpusTimeline(CONFIG).update_timeline_item(followup_id=followup_id, version=version, changes=changes)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_timeline_item done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_timeline_item(followup_id: str) -> dict:
        """Read the current agenda item and version.

        Args:
            followup_id: Followup id.
        """
        logger.info("Tool called: get_hfl_corpus_timeline_item")
        result = ApiServiceHflCorpusTimeline(CONFIG).get_timeline_item(followup_id=followup_id)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_timeline_item done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_timeline_history(followup_id: str) -> dict:
        """Read immutable agenda revisions and rendered completion notes.

        Args:
            followup_id: Followup id.
        """
        logger.info("Tool called: get_hfl_corpus_timeline_history")
        result = ApiServiceHflCorpusTimeline(CONFIG).get_timeline_history(followup_id=followup_id)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_timeline_history done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_timeline_markers(
        query: str = '',
        source: str = '',
        date_field: str = 'created',
        date_from: str = '',
        date_to: str = '',
        rolling: int = 0,
        scope: dict | None = None,
    ) -> dict:
        """Read scoped action date markers and aggregate statuses.

        Args:
            query: Search text; empty means no text filter.
            source: Source.
            date_field: Date field.
            date_from: Date from.
            date_to: Date to.
            rolling: Rolling.
            scope: Optional combined-view object with any/all filter clauses.
        """
        logger.info("Tool called: get_hfl_corpus_timeline_markers")
        result = ApiServiceHflCorpusTimeline(CONFIG).get_timeline_markers(query=query, source=source, date_field=date_field, date_from=date_from, date_to=date_to, rolling=rolling, scope=scope)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_timeline_markers done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_timeline_period(
        start: str,
        end: str,
        query: str = '',
        source: str = '',
        date_field: str = 'created',
        date_from: str = '',
        date_to: str = '',
        rolling: int = 0,
        scope: dict | None = None,
    ) -> dict:
        """Read agenda items, suggestions, receipts and exploration state for 1–31 inclusive days.

        Args:
            start: Inclusive start date, YYYY-MM-DD.
            end: Inclusive end date, YYYY-MM-DD.
            query: Search text; empty means no text filter.
            source: Source.
            date_field: Date field.
            date_from: Date from.
            date_to: Date to.
            rolling: Rolling.
            scope: Optional combined-view object with any/all filter clauses.
        """
        logger.info("Tool called: get_hfl_corpus_timeline_period")
        result = ApiServiceHflCorpusTimeline(CONFIG).get_timeline_period(start=start, end=end, query=query, source=source, date_field=date_field, date_from=date_from, date_to=date_to, rolling=rolling, scope=scope)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_timeline_period done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_timeline_suggestion_dismiss(sid: str) -> dict:
        """Dismiss an idea/suggestion. Destructive: writes remote state.

        Args:
            sid: Sid.
        """
        logger.info("Tool called: update_hfl_corpus_timeline_suggestion_dismiss")
        result = ApiServiceHflCorpusTimeline(CONFIG).update_timeline_suggestion_dismiss(sid=sid)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_timeline_suggestion_dismiss done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_timeline_exploration(start: str, end: str) -> dict:
        """Schedule AI exploration for 1–31 days ending today or earlier; may incur model usage. Destructive: writes remote state.

        Args:
            start: Inclusive start date, YYYY-MM-DD.
            end: Inclusive end date, YYYY-MM-DD.
        """
        logger.info("Tool called: create_hfl_corpus_timeline_exploration")
        result = ApiServiceHflCorpusTimeline(CONFIG).create_timeline_exploration(start=start, end=end)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_timeline_exploration done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_ideas_snapshot() -> dict:
        """Read ideas, maps, links, goals and visible graph context.
        """
        logger.info("Tool called: get_hfl_corpus_ideas_snapshot")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_ideas_snapshot()
        output = _dict_result(result)
        logger.info("get_hfl_corpus_ideas_snapshot done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_connection_availability() -> dict:
        """Read available object connection choices.
        """
        logger.info("Tool called: get_hfl_corpus_connection_availability")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_connection_availability()
        output = _dict_result(result)
        logger.info("get_hfl_corpus_connection_availability done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_action_connections(identity: str) -> dict:
        """Read an action’s graph connections.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_action_connections")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_action_connections(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_action_connections done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_date_connections(identity: str) -> dict:
        """Read a date pin’s graph connections.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_date_connections")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_date_connections(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_date_connections done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_idea_connections(identity: str) -> dict:
        """Read an idea's graph connections.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_idea_connections")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_idea_connections(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_idea_connections done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_boards() -> dict:
        """Read board metadata, goals and the color palette without scanning the corpus.
        """
        logger.info("Tool called: list_hfl_corpus_boards")
        result = ApiServiceHflCorpusIdeas(CONFIG).list_boards()
        output = _dict_result(result)
        logger.info("list_hfl_corpus_boards done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_board_order(ids: list[str]) -> dict:
        """Persist board ordering. Destructive: writes remote state.

        Args:
            ids: Ids.
        """
        logger.info("Tool called: update_hfl_corpus_board_order")
        result = ApiServiceHflCorpusIdeas(CONFIG).update_board_order(ids=ids)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_board_order done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_goal_order(ids: list[str]) -> dict:
        """Persist goal ordering. Destructive: writes remote state.

        Args:
            ids: Ids.
        """
        logger.info("Tool called: update_hfl_corpus_goal_order")
        result = ApiServiceHflCorpusIdeas(CONFIG).update_goal_order(ids=ids)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_goal_order done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_goal_options() -> dict:
        """List visible ideas/actions that can be linked to goals.
        """
        logger.info("Tool called: get_hfl_corpus_goal_options")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_goal_options()
        output = _dict_result(result)
        logger.info("get_hfl_corpus_goal_options done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_map(identity: str) -> dict:
        """Read a mind map and current version.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_map")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_map(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_map done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_map_graph(identity: str) -> dict:
        """Read the visible graph projection for map members.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_map_graph")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_map_graph(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_map_graph done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_map_attach_options(identity: str, query: str = '', offset: int = 0) -> dict:
        """Search attachable objects; returns 50 per page.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            query: Search text; empty means no text filter.
            offset: Nonnegative pagination offset.
        """
        logger.info("Tool called: list_hfl_corpus_map_attach_options")
        result = ApiServiceHflCorpusIdeas(CONFIG).list_map_attach_options(identity=identity, query=query, offset=offset)
        output = _dict_result(result)
        logger.info("list_hfl_corpus_map_attach_options done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_rendered_markdown(body: str) -> dict:
        """Render up to 60000 characters of Markdown using the frontend renderer. Read-only.

        Args:
            body: Body.
        """
        logger.info("Tool called: get_hfl_corpus_rendered_markdown")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_rendered_markdown(body=body)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_rendered_markdown done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_idea(identity: str) -> dict:
        """Read an idea, version and rendered content.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_idea")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_idea(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_idea done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_idea(request_id: str, title: str, fields: dict | None = None) -> dict:
        """Create an idea; reuse the request UUID for stable identity. Destructive: writes remote state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            title: Title.
            fields: Optional description, body, checklists, status, source, expected_outcome, matrix, matrix_confidence, matrix_reason, source_date.
        """
        logger.info("Tool called: create_hfl_corpus_idea")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_idea(request_id=request_id, title=title, fields=fields)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_idea done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_idea(identity: str, version: int, changes: dict) -> dict:
        """Edit/dismiss/restore an idea using the latest version. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Changed title, description, body, checklists, status, source, expected_outcome, matrix, matrix_confidence, matrix_reason, source_date.
        """
        logger.info("Tool called: update_hfl_corpus_idea")
        result = ApiServiceHflCorpusIdeas(CONFIG).update_idea(identity=identity, version=version, changes=changes)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_idea done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_topic(label: str) -> dict:
        """Create a named graph topic and initial entity profile; URLs are not topic names. Destructive: writes remote state.

        Args:
            label: Label.
        """
        logger.info("Tool called: create_hfl_corpus_topic")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_topic(label=label)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_topic done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_link(source: str, target: str, relation: str = 'related-to') -> dict:
        """Create a durable relation between visible graph nodes. Destructive: writes remote state.

        Args:
            source: Source.
            target: Target.
            relation: Relation.
        """
        logger.info("Tool called: create_hfl_corpus_link")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_link(source=source, target=target, relation=relation)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_link done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def delete_hfl_corpus_link(source: str, target: str, relation: str = 'related-to') -> dict:
        """Delete a durable relation between visible graph nodes. Destructive: writes remote state.

        Args:
            source: Source.
            target: Target.
            relation: Relation.
        """
        logger.info("Tool called: delete_hfl_corpus_link")
        result = ApiServiceHflCorpusIdeas(CONFIG).delete_link(source=source, target=target, relation=relation)
        output = _dict_result(result)
        logger.info("delete_hfl_corpus_link done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_map(request_id: str, name: str, fields: dict | None = None) -> dict:
        """Create a versioned mind map; UUID determines its stable identity. Destructive: writes remote state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            name: Map name, 1–100 characters.
            fields: Optional members, positions, node_sizes, edge_widths, prompt, purpose, root, goal_id, drafts, edges, board_date and color.
        """
        logger.info("Tool called: create_hfl_corpus_map")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_map(request_id=request_id, name=name, fields=fields)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_map done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_map(identity: str, version: int, changes: dict) -> dict:
        """Update map membership/content/layout with an optimistic version check. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Map fields to change: name, members, positions, node_sizes, edge_widths, prompt, purpose, root, goal_id, drafts, edges, board_date, color.
        """
        logger.info("Tool called: update_hfl_corpus_map")
        result = ApiServiceHflCorpusIdeas(CONFIG).update_map(identity=identity, version=version, changes=changes)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_map done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def delete_hfl_corpus_map(identity: str, version: int) -> dict:
        """Delete a map using its latest version; shared objects remain independently owned. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
        """
        logger.info("Tool called: delete_hfl_corpus_map")
        result = ApiServiceHflCorpusIdeas(CONFIG).delete_map(identity=identity, version=version)
        output = _dict_result(result)
        logger.info("delete_hfl_corpus_map done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_map_promotion(identity: str, draft_id: str, version: int) -> dict:
        """Promote a map draft into a durable idea. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            draft_id: Draft id.
            version: Latest object version; stale writes return 409. Read before retrying.
        """
        logger.info("Tool called: create_hfl_corpus_map_promotion")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_map_promotion(identity=identity, draft_id=draft_id, version=version)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_map_promotion done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_goal(identity: str) -> dict:
        """Read a goal with its current version.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: get_hfl_corpus_goal")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_goal(identity=identity)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_goal done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_map_link_promotion(
        identity: str,
        source: str,
        target: str,
        version: int,
        relation: str = 'related-to',
    ) -> dict:
        """Promote a map connection to a durable graph relation. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            source: Source.
            target: Target.
            version: Latest object version; stale writes return 409. Read before retrying.
            relation: Relation.
        """
        logger.info("Tool called: create_hfl_corpus_map_link_promotion")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_map_link_promotion(identity=identity, source=source, target=target, version=version, relation=relation)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_map_link_promotion done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_map_connection(identity: str, changes: dict) -> dict:
        """Edit a board connection using its current board/edge revision. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            changes: Command: operation (create/update/remove/width), scope (local/shared), edge {source,target,relation,direction}, replacement (optional), version, revision for shared edges, width for width operations.
        """
        logger.info("Tool called: update_hfl_corpus_map_connection")
        result = ApiServiceHflCorpusIdeas(CONFIG).update_map_connection(identity=identity, changes=changes)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_map_connection done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_goal(request_id: str, title: str, fields: dict | None = None) -> dict:
        """Create a durable goal with validated idea/action links. Destructive: writes remote state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            title: Title.
            fields: Optional body, success_criteria, status, target_date, progress_notes, milestones, linked_objects and color.
        """
        logger.info("Tool called: create_hfl_corpus_goal")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_goal(request_id=request_id, title=title, fields=fields)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_goal done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_goal(identity: str, version: int, changes: dict) -> dict:
        """Update a goal with optimistic concurrency and validated milestone links. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Changed title, body, success_criteria, status, target_date, progress_notes, milestones, linked_objects or color.
        """
        logger.info("Tool called: update_hfl_corpus_goal")
        result = ApiServiceHflCorpusIdeas(CONFIG).update_goal(identity=identity, version=version, changes=changes)
        output = _dict_result(result)
        logger.info("update_hfl_corpus_goal done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_idea_conversion(identity: str, checklist_id: str = '', item_id: str = '') -> dict:
        """Preview conversion of an idea or checklist item into an action.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            checklist_id: Checklist id.
            item_id: Item id.
        """
        logger.info("Tool called: get_hfl_corpus_idea_conversion")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_idea_conversion(identity=identity, checklist_id=checklist_id, item_id=item_id)
        output = _dict_result(result)
        logger.info("get_hfl_corpus_idea_conversion done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_idea_conversion(
        identity: str,
        request_id: str,
        idea_version: int,
        item: dict,
        attachments: list[str] | None = None,
        checklist_id: str = '',
        item_id: str = '',
    ) -> dict:
        """Convert an idea to an action, clone selected attachments, and mark it adopted. Agent execution remains disabled. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            idea_version: Idea version.
            item: Action draft returned by get_hfl_corpus_idea_conversion, with any reviewed field edits.
            attachments: Attachment IDs to clone, not local file paths.
            checklist_id: Checklist id.
            item_id: Item id.
        """
        logger.info("Tool called: create_hfl_corpus_idea_conversion")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_idea_conversion(identity=identity, request_id=request_id, idea_version=idea_version, item=item, attachments=attachments, checklist_id=checklist_id, item_id=item_id)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_idea_conversion done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_idea_attachments(identity: str) -> dict:
        """List an idea’s supporting files.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        logger.info("Tool called: list_hfl_corpus_idea_attachments")
        result = ApiServiceHflCorpusIdeas(CONFIG).list_idea_attachments(identity=identity)
        output = _dict_result(result)
        logger.info("list_hfl_corpus_idea_attachments done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def download_hfl_corpus_idea_attachment(identity: str, attachment_id: str, destination: str) -> dict:
        """Download a supporting file to a local path; replaces an existing destination. Destructive: writes a local file.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            attachment_id: Attachment ID from the list/upload response.
            destination: Local destination file path on the MCP host.
        """
        logger.info("Tool called: download_hfl_corpus_idea_attachment")
        result = ApiServiceHflCorpusIdeas(CONFIG).download_idea_attachment(identity=identity, attachment_id=attachment_id, destination=destination)
        output = _dict_result(result)
        logger.info("download_hfl_corpus_idea_attachment done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def upload_hfl_corpus_idea_attachments(identity: str, file_paths: list[str]) -> dict:
        """Attach supporting files to an idea; at most 50 files of 500 MB each. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            file_paths: Local readable file paths on the MCP host.
        """
        logger.info("Tool called: upload_hfl_corpus_idea_attachments")
        result = ApiServiceHflCorpusIdeas(CONFIG).upload_idea_attachments(identity=identity, file_paths=file_paths)
        output = _dict_result(result)
        logger.info("upload_hfl_corpus_idea_attachments done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def delete_hfl_corpus_idea_attachment(identity: str, attachment_id: str) -> dict:
        """Detach a supporting file from an idea. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            attachment_id: Attachment ID from the list/upload response.
        """
        logger.info("Tool called: delete_hfl_corpus_idea_attachment")
        result = ApiServiceHflCorpusIdeas(CONFIG).delete_idea_attachment(identity=identity, attachment_id=attachment_id)
        output = _dict_result(result)
        logger.info("delete_hfl_corpus_idea_attachment done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_map_proposal(
        identity: str,
        request_id: str,
        item: dict,
        parents: list[str] | None = None,
    ) -> dict:
        """Accept a proposed thought into a map with at most five existing parents. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            item: Proposed title, description and/or body only.
            parents: Parents.
        """
        logger.info("Tool called: create_hfl_corpus_map_proposal")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_map_proposal(identity=identity, request_id=request_id, item=item, parents=parents)
        output = _dict_result(result)
        logger.info("create_hfl_corpus_map_proposal done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_day_matches(
        activity_day: str,
        query: str = '',
        source: str = '',
        offset: int = 0,
        limit: int = 20,
        include_secrets: bool = False,
        secret_tags: str = '',
        scope: dict | None = None,
    ) -> dict:
        """Read matching entries across documents for one YYYY-MM-DD activity date; maximum 20 per page.

        Args:
            activity_day: Activity day.
            query: Search text; empty means no text filter.
            source: Source.
            offset: Nonnegative pagination offset.
            limit: Maximum results; subject to server limits.
            include_secrets: Include secrets.
            secret_tags: Secret tags.
            scope: Optional combined-view object with any/all filter clauses.
        """
        logger.info("Tool called: list_hfl_corpus_day_matches")
        result = ApiServiceHflCorpusCalendar(CONFIG).list_day_matches(activity_day=activity_day, query=query, source=source, offset=offset, limit=limit, include_secrets=include_secrets, secret_tags=secret_tags, scope=scope)
        output = _dict_result(result)
        logger.info("list_hfl_corpus_day_matches done")
        return output

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_reuse_options(query: str='', page: int=1) -> dict:
        """Search actions and ideas available for independent copying."""
        logger.info("Tool called: list_hfl_corpus_reuse_options")
        result = ApiServiceHflCorpusIdeas(CONFIG).list_reuse_options(query=query, page=page)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_hfl_corpus_board_ideas(dismissed: bool=False) -> dict:
        """List visible ideas available to boards, optionally including dismissed ideas."""
        logger.info("Tool called: list_hfl_corpus_board_ideas")
        result = ApiServiceHflCorpusIdeas(CONFIG).list_board_ideas(dismissed=dismissed)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_clone_draft(kind: str, identity: str) -> dict:
        """Preview an independent action or idea copy without saving it."""
        logger.info("Tool called: get_hfl_corpus_clone_draft")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_clone_draft(kind=kind, identity=identity)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_clone(kind: str, identity: str, request_id: str, source_version: int, item: dict, attachments: list[str] | None=None) -> dict:
        """Create a copy using a caller UUID and the source revision. Writes remote state."""
        logger.info("Tool called: create_hfl_corpus_clone")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_clone(kind=kind, identity=identity, request_id=request_id, source_version=source_version, item=item, attachments=attachments)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_list_copy(kind: str, identity: str, request_id: str, version: int, checklist: dict) -> dict:
        """Copy a checklist into an action or idea at the expected revision. Writes remote state."""
        logger.info("Tool called: create_hfl_corpus_list_copy")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_list_copy(kind=kind, identity=identity, request_id=request_id, version=version, checklist=checklist)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_map_paste(identity: str, request_id: str, version: int, source_board: str, source_version: int, selected: list[str]) -> dict:
        """Paste selected objects between versioned boards. Writes remote state."""
        logger.info("Tool called: create_hfl_corpus_map_paste")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_map_paste(identity=identity, request_id=request_id, version=version, source_board=source_board, source_version=source_version, selected=selected)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_hfl_corpus_list(identity: str) -> dict:
        """Read a standalone or owner-linked checklist entity."""
        logger.info("Tool called: get_hfl_corpus_list")
        result = ApiServiceHflCorpusIdeas(CONFIG).get_list(identity=identity)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_list(request_id: str, checklist: dict) -> dict:
        """Create a standalone checklist with a caller-generated UUID. Writes remote state."""
        logger.info("Tool called: create_hfl_corpus_list")
        result = ApiServiceHflCorpusIdeas(CONFIG).create_list(request_id=request_id, checklist=checklist)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_list(identity: str, version: int, checklist: dict) -> dict:
        """Update a standalone or owner-linked checklist at its expected revision. Writes remote state."""
        logger.info("Tool called: update_hfl_corpus_list")
        result = ApiServiceHflCorpusIdeas(CONFIG).update_list(identity=identity, version=version, checklist=checklist)
        return _dict_result(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity_type(name: str, color: str, description: str) -> dict:
        """Create a type with a name, hex color and extraction description. History is not reprocessed."""
        return _dict_result(ApiServiceHflCorpusEntities(CONFIG).create_entity_type(name=name, color=color, description=description))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity(name: str, kind: str, categories: list[str] | None = None,
                                 emails: list[str] | None = None, phones: list[str] | None = None,
                                 references: list[str] | None = None, notes: str = '') -> dict:
        """Create a manual entity of a configured type with optional profile details."""
        return _dict_result(ApiServiceHflCorpusEntities(CONFIG).create_entity(name=name, kind=kind,
            categories=categories, emails=emails, phones=phones, references=references, notes=notes))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def update_hfl_corpus_entity_type(identity: str, kind: str) -> dict:
        """Change an entity to a configured type, preserving its profile."""
        return _dict_result(ApiServiceHflCorpusEntities(CONFIG).update_entity_type(identity=identity, kind=kind))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def create_hfl_corpus_entity_merge_batch(groups: list[dict]) -> dict:
        """Commit up to 100 disjoint groups after user review. Each group needs entity_ids,
        name, request_id (UUID) and preview_token from analyze_hfl_corpus_entity_selection;
        evidence and profile edits are optional. Reuse identical payloads and request IDs
        on retry. Returns a result or error per group; partial success is possible.
        """
        return _dict_result(ApiServiceHflCorpusEntities(CONFIG).create_entity_merge_batch(groups=groups))
