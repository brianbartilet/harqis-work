import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from apps.confluence.config import CONFIG
from apps.confluence.references.web.api.content import ApiServiceConfluenceContent

logger = logging.getLogger("harqis-mcp.confluence")


def register_confluence_tools(mcp: FastMCP):

    @mcp.tool()
    def confluence_search(cql: str, limit: int = 25, start: int = 0) -> dict:
        """Search Confluence content with CQL (Confluence Query Language).

        Example CQL:
            "space = ENG and type = page order by lastmodified desc"
            "text ~ 'OAuth token refresh' and type = page"

        Args:
            cql:   CQL query string.
            limit: Page size (default 25).
            start: Pagination offset (default 0).

        Returns:
            Dict with keys: results (list of content), size, totalSize.
        """
        logger.info("Tool called: confluence_search cql=%s", cql)
        result = ApiServiceConfluenceContent(CONFIG).search_cql(cql=cql, limit=limit, start=start)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def confluence_get_page(page_id: str, expand: Optional[str] = None) -> dict:
        """Get a single Confluence page by id (body + version + labels expanded).

        Args:
            page_id: Numeric content id.
            expand:  Override the default expansion set
                     (body.storage,version,space,ancestors,metadata.labels).
        """
        logger.info("Tool called: confluence_get_page page_id=%s", page_id)
        result = ApiServiceConfluenceContent(CONFIG).get_page(page_id=page_id, expand=expand)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def confluence_list_spaces(limit: int = 50, space_type: Optional[str] = None) -> dict:
        """List Confluence spaces visible to the configured token.

        Args:
            limit:      Page size (default 50).
            space_type: Optional filter — 'global' or 'personal'.
        """
        logger.info("Tool called: confluence_list_spaces type=%s", space_type)
        result = ApiServiceConfluenceContent(CONFIG).list_spaces(limit=limit, space_type=space_type)
        return result if isinstance(result, dict) else {}
