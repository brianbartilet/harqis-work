import logging
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from apps.notion.config import CONFIG
from apps.notion.references.web.api.databases import ApiServiceNotionDatabases
from apps.notion.references.web.api.pages import ApiServiceNotionPages
from apps.notion.references.web.api.blocks import ApiServiceNotionBlocks
from apps.notion.references.web.api.users import ApiServiceNotionUsers
from apps.notion.references.web.api.search import ApiServiceNotionSearch

logger = logging.getLogger("harqis-mcp.notion")


def register_notion_tools(mcp: FastMCP):

    # ── Databases ────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_notion_database(database_id: str) -> dict:
        """
        Retrieve a Notion database by its ID.

        Args:
            database_id: The database's UUID (with or without dashes).
        """
        logger.info("Tool called: get_notion_database database_id=%s", database_id)
        result = ApiServiceNotionDatabases(CONFIG).get_database(database_id)
        result = result if isinstance(result, dict) else {}
        logger.info("get_notion_database title=%s", result.get("title"))
        return result

    @mcp.tool()
    def query_notion_database(database_id: str, filter: dict = None,
                              sorts: list = None, page_size: int = 100) -> dict:
        """
        Query pages in a Notion database with optional filter and sort.

        Args:
            database_id: The database's UUID.
            filter:      Notion filter object (see https://developers.notion.com/reference/post-database-query-filter).
            sorts:       List of sort objects.
            page_size:   Number of results (max 100, default 100).
        """
        logger.info("Tool called: query_notion_database database_id=%s", database_id)
        result = ApiServiceNotionDatabases(CONFIG).query_database(
            database_id, filter=filter, sorts=sorts, page_size=page_size
        )
        result = result if isinstance(result, dict) else {}
        logger.info("query_notion_database returned %d result(s)", len(result.get("results", [])))
        return result

    @mcp.tool()
    def create_notion_database(parent_page_id: str, title: str,
                               properties: dict = None) -> dict:
        """
        Create a new inline database as a child of a Notion page.

        Args:
            parent_page_id: UUID of the parent page.
            title:          Database title.
            properties:     Property schema dict. Defaults to a single 'Name' title property.
        """
        logger.info("Tool called: create_notion_database title=%s", title)
        result = ApiServiceNotionDatabases(CONFIG).create_database(
            parent_page_id=parent_page_id, title=title, properties=properties
        )
        result = result if isinstance(result, dict) else {}
        logger.info("create_notion_database created id=%s", result.get("id"))
        return result

    # ── Pages ────────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_notion_page(page_id: str) -> dict:
        """
        Retrieve a Notion page by its ID.

        Args:
            page_id: The page's UUID (with or without dashes).
        """
        logger.info("Tool called: get_notion_page page_id=%s", page_id)
        result = ApiServiceNotionPages(CONFIG).get_page(page_id)
        result = result if isinstance(result, dict) else {}
        logger.info("get_notion_page url=%s", result.get("url"))
        return result

    @mcp.tool()
    def create_notion_page(parent: dict, properties: dict,
                           children: list = None) -> dict:
        """
        Create a new page in a Notion database or as a child of another page.

        Args:
            parent:     Parent object — e.g. {'database_id': '<id>'} or {'page_id': '<id>'}.
            properties: Property values matching the parent database schema.
                        For a database page: {'Name': {'title': [{'text': {'content': 'My task'}}]}}
                        For a sub-page:      {'title': [{'text': {'content': 'My sub-page'}}]}
            children:   Optional list of block objects to add as initial page content.
        """
        logger.info("Tool called: create_notion_page parent=%s", parent)
        result = ApiServiceNotionPages(CONFIG).create_page(
            parent=parent, properties=properties, children=children
        )
        result = result if isinstance(result, dict) else {}
        logger.info("create_notion_page created id=%s", result.get("id"))
        return result

    @mcp.tool()
    def update_notion_page(page_id: str, properties: dict = None,
                           archived: bool = None) -> dict:
        """
        Update a Notion page's properties or archive/unarchive it.

        Args:
            page_id:    The page's UUID.
            properties: Updated property values (optional).
            archived:   True to archive the page, False to restore it (optional).
        """
        logger.info("Tool called: update_notion_page page_id=%s archived=%s", page_id, archived)
        result = ApiServiceNotionPages(CONFIG).update_page(
            page_id=page_id, properties=properties, archived=archived
        )
        result = result if isinstance(result, dict) else {}
        return result

    # ── Blocks ───────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_notion_block_children(block_id: str, page_size: int = 100) -> dict:
        """
        Retrieve all child blocks of a Notion page or block.

        Args:
            block_id:  The parent page or block UUID.
            page_size: Number of results (max 100, default 100).
        """
        logger.info("Tool called: get_notion_block_children block_id=%s", block_id)
        result = ApiServiceNotionBlocks(CONFIG).get_block_children(block_id, page_size=page_size)
        result = result if isinstance(result, dict) else {}
        logger.info("get_notion_block_children returned %d block(s)", len(result.get("results", [])))
        return result

    @mcp.tool()
    def append_notion_block_children(block_id: str, children: list) -> dict:
        """
        Append new blocks to a Notion page or block.

        Args:
            block_id: Parent page or block UUID.
            children: List of block objects to append.

        Example children:
            [{'object': 'block', 'type': 'paragraph',
              'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': 'Hello'}}]}}]
        """
        logger.info("Tool called: append_notion_block_children block_id=%s count=%d", block_id, len(children))
        result = ApiServiceNotionBlocks(CONFIG).append_block_children(block_id, children=children)
        result = result if isinstance(result, dict) else {}
        return result

    # ── Users ────────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_notion_me() -> dict:
        """Get the bot user associated with the current Notion integration token."""
        logger.info("Tool called: get_notion_me")
        result = ApiServiceNotionUsers(CONFIG).get_me()
        result = result if isinstance(result, dict) else {}
        logger.info("get_notion_me name=%s", result.get("name"))
        return result

    @mcp.tool()
    def list_notion_users(page_size: int = 100) -> dict:
        """
        List all users in the Notion workspace.

        Args:
            page_size: Number of results (max 100, default 100).
        """
        logger.info("Tool called: list_notion_users")
        result = ApiServiceNotionUsers(CONFIG).list_users(page_size=page_size)
        result = result if isinstance(result, dict) else {}
        logger.info("list_notion_users returned %d user(s)", len(result.get("results", [])))
        return result

    # ── Search ───────────────────────────────────────────────────────────────

    @mcp.tool()
    def search_notion(query: str = None, filter_object: str = None,
                      page_size: int = 20) -> dict:
        """
        Search all pages and databases accessible to the Notion integration.

        Args:
            query:         Plain-text search query. Returns all results if omitted.
            filter_object: Limit results to 'page' or 'database' (optional).
            page_size:     Number of results (max 100, default 20).
        """
        logger.info("Tool called: search_notion query=%s filter=%s", query, filter_object)
        result = ApiServiceNotionSearch(CONFIG).search(
            query=query, filter_object=filter_object, page_size=page_size
        )
        result = result if isinstance(result, dict) else {}
        logger.info("search_notion returned %d result(s)", len(result.get("results", [])))
        return result
