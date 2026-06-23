from typing import List, Optional

from apps.confluence.references.web.base_api_service import BaseApiServiceConfluence
from core.web.services.core.decorators.deserializer import deserialized

# Default expand set for a page read — body, version (for incremental sync),
# space, ancestors (breadcrumb), and labels (deterministic topic tags).
_PAGE_EXPAND = "body.storage,version,space,ancestors,metadata.labels"


class ApiServiceConfluenceContent(BaseApiServiceConfluence):
    """
    Confluence REST API — content (pages) operations.

    Methods:
        search_cql()       → Search pages with CQL (Confluence Query Language)
        get_page()         → Single page by id, with body/version/labels expanded
        get_descendants()  → Child pages under a page (subtree ingest)
        list_spaces()      → Spaces visible to the token
        get_labels()       → Labels on a page
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceConfluenceContent, self).__init__(config, **kwargs)

    @deserialized(dict)
    def search_cql(self, cql: str, limit: int = 50, start: int = 0,
                   expand: Optional[str] = None):
        """
        Search content using CQL.

        Args:
            cql:    CQL query, e.g. "space in (ENG, OPS) and type = page
                    order by lastmodified desc". For incremental sync append
                    "and lastmodified >= '2026-06-01'".
            limit:  Page size (default 50, Confluence caps at 100/200).
            start:  Pagination offset (default 0).
            expand: Comma-separated expansions applied to each result. Defaults
                    to version + space + labels so a search result already
                    carries enough metadata to decide whether to re-ingest.

        Returns:
            Dict with keys: results (list), size, start, limit, totalSize.
        """
        self.request.get() \
            .add_uri_parameter('content') \
            .add_uri_parameter('search') \
            .add_query_string('cql', cql) \
            .add_query_string('limit', limit) \
            .add_query_string('start', start) \
            .add_query_string('expand', expand or "version,space,metadata.labels")

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_page(self, page_id: str, expand: Optional[str] = None):
        """
        Get a single page by id.

        Args:
            page_id: Numeric content id (string).
            expand:  Comma-separated expansions. Defaults to body.storage +
                     version + space + ancestors + labels.
        """
        self.request.get() \
            .add_uri_parameter('content') \
            .add_uri_parameter(page_id) \
            .add_query_string('expand', expand or _PAGE_EXPAND)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_descendants(self, page_id: str, limit: int = 100, start: int = 0,
                        expand: Optional[str] = None):
        """
        Get descendant pages under a page — the whole subtree, paginated.

        Args:
            page_id: Ancestor content id.
            limit:   Page size (default 100).
            start:   Pagination offset.
            expand:  Expansions per child (defaults to version + labels).
        """
        self.request.get() \
            .add_uri_parameter('content') \
            .add_uri_parameter(page_id) \
            .add_uri_parameter('descendant') \
            .add_uri_parameter('page') \
            .add_query_string('limit', limit) \
            .add_query_string('start', start) \
            .add_query_string('expand', expand or "version,metadata.labels")

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_spaces(self, limit: int = 50, start: int = 0,
                    space_type: Optional[str] = None):
        """
        List spaces visible to the configured token.

        Args:
            limit:      Page size (default 50).
            start:      Pagination offset.
            space_type: Optional filter — 'global' or 'personal'.
        """
        self.request.get() \
            .add_uri_parameter('space') \
            .add_query_string('limit', limit) \
            .add_query_string('start', start)
        if space_type:
            self.request.add_query_string('type', space_type)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_labels(self, page_id: str):
        """
        Get the labels attached to a page.

        Args:
            page_id: Content id.
        """
        self.request.get() \
            .add_uri_parameter('content') \
            .add_uri_parameter(page_id) \
            .add_uri_parameter('label')

        return self.client.execute_request(self.request.build())
