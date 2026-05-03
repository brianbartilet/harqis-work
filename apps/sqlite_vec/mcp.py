"""MCP tools — local sqlite-vec vector store inspection."""
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from apps.sqlite_vec import store

logger = logging.getLogger("harqis-mcp.sqlite_vec")


def register_sqlite_vec_tools(mcp: FastMCP):

    @mcp.tool()
    def vector_store_stats() -> dict:
        """Return total chunk count and per-source counts for the local vector store.

        Use this to sanity-check ingestion (did the Notion ingest task actually
        write rows?) without firing a query.
        """
        logger.info("Tool called: vector_store_stats")
        s = store.stats()
        logger.info("vector_store_stats total=%d sources=%s", s.get("total", 0), list(s.get("by_source", {}).keys()))
        return s

    @mcp.tool()
    def vector_store_search_text(
        query_embedding: list[float],
        k: int = 5,
        source: Optional[str] = None,
    ) -> list[dict]:
        """Run a KNN search against the local vector store and return chunk payloads.

        This tool expects a pre-computed embedding — pair it with
        `gemini_embed_content(task_type='RETRIEVAL_QUERY')` to get the vector.
        For end-to-end question answering call the `knowledge_ask` workflow
        tool instead.

        Args:
            query_embedding: The query vector (must match the indexed dim).
            k:               Number of top results to return (default 5).
            source:          Restrict to one corpus label (e.g. 'notion').
        """
        logger.info("Tool called: vector_store_search_text k=%d source=%s", k, source)
        return store.search(query_embedding, k=k, source=source)

    @mcp.tool()
    def vector_store_delete_source(source: str) -> dict:
        """Delete every chunk in a given source. Use before a full re-ingest.

        Args:
            source: The source label to clear (e.g. 'notion').
        """
        logger.info("Tool called: vector_store_delete_source source=%s", source)
        n = store.delete_by_source(source)
        return {"deleted": n, "source": source}
