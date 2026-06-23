"""MCP tools — high-level RAG over the local knowledge base.

Exposes the end-to-end answer pipeline as `knowledge_ask` so Claude Desktop
can call it directly without first computing an embedding by hand.
"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from apps.sqlite_vec import store
from workflows.knowledge.retriever import retrieve
from workflows.knowledge.tasks.answer import answer_question, _DEFAULT_HAIKU

logger = logging.getLogger("harqis-mcp.knowledge")


def register_knowledge_tools(mcp: FastMCP):

    @mcp.tool()
    def knowledge_search(question: str, k: int = 5, source: Optional[str] = None) -> list[dict]:
        """Retrieve top-k snippets from the local knowledge base for a question.

        No LLM call — just embedding + KNN. Use this when you want to inspect
        what the retriever finds before paying for generation.

        Args:
            question: Natural-language query.
            k:        Number of snippets to return (default 5).
            source:   Restrict to a corpus label, e.g. 'notion'.
        """
        logger.info("Tool called: knowledge_search k=%d source=%s", k, source)
        hits = retrieve(question, k=k, source=source)
        return [
            {
                "id": h["id"],
                "source": h["source"],
                "ref": h["ref"],
                "text": h["text"],
                "distance": h["distance"],
            }
            for h in hits
        ]

    @mcp.tool()
    def knowledge_ask(
        question: str,
        k: int = 5,
        source: Optional[str] = None,
        model: str = _DEFAULT_HAIKU,
    ) -> dict:
        """Answer a question grounded in the local knowledge base.

        Pipeline: embed query (Gemini RETRIEVAL_QUERY) → KNN against sqlite_vec
        → Anthropic generates a cited answer. Defaults to Claude Haiku 4.5 for
        cost. Pass `model='claude-sonnet-4-6'` for harder questions.

        Args:
            question: Natural-language query.
            k:        Top-k retrieval (default 5).
            source:   Restrict to a corpus label, e.g. 'notion'.
            model:    Override generation model.

        Returns:
            Dict with: answer (string with [n] citations), hits (id/ref/source
            for each cited snippet), model.
        """
        logger.info("Tool called: knowledge_ask source=%s model=%s", source, model)
        return answer_question(question=question, k=k, source=source, model=model)

    # ---------------------------------------------------------------- #
    # Phase 1 / Phase 3 — learning, relations, and cross-source radar
    # ---------------------------------------------------------------- #

    @mcp.tool()
    def knowledge_list_sources() -> dict:
        """List indexed corpora and their chunk counts (e.g. confluence, jira,
        github, hfl). Use this to see what the knowledge base currently covers."""
        logger.info("Tool called: knowledge_list_sources")
        return store.stats()

    @mcp.tool()
    def knowledge_topic_map(topic: str, k: int = 12, model: str = _DEFAULT_HAIKU) -> dict:
        """Learn a topic and how it connects across teams.

        Retrieves across every source, then returns a cited learning brief:
        what it is, how it works, integrations & dependencies, business value,
        related tickets/docs/PRs, and what to learn next — plus the extracted
        entities and the per-source hit list so the answer is auditable.

        Args:
            topic: e.g. "OAuth token refresh" or "Payments settlement flow".
            k:     Snippets to ground the brief on (default 12).
            model: Anthropic model (default Haiku 4.5).
        """
        from workflows.knowledge.tasks.topic_map import topic_map
        logger.info("Tool called: knowledge_topic_map topic=%s", topic)
        return topic_map(topic, k=k, model=model)

    @mcp.tool()
    def knowledge_relations(query: str, k: int = 12) -> dict:
        """Map how a topic/entity connects across sources.

        Returns a small graph: nodes (top chunks from each source) and edges
        between nodes that share an explicit entity (Jira key, service name,
        PR ref). Use it to see integrations and dependencies at a glance.

        Args:
            query: A topic or an entity like 'PAY-1421' or 'Payments'.
            k:     Nodes to consider (default 12).
        """
        from workflows.knowledge.tasks.cross_link import relations
        logger.info("Tool called: knowledge_relations query=%s", query)
        return relations(query, k=k)

    @mcp.tool()
    def knowledge_working_context(since: str = "-3d", k: int = 8, summarize: bool = True) -> dict:
        """Infer what you're currently working on (from HFL signal) and surface
        the indexed docs/tickets/PRs that connect to it.

        Args:
            since:     Window for recent activity (ISO date or relative "-Nd").
            k:         Signals to read / related hits to return.
            summarize: Add a short cited Anthropic brief tying it together.
        """
        from workflows.knowledge.tasks.cross_link import working_context
        logger.info("Tool called: knowledge_working_context since=%s", since)
        return working_context(since=since, k=k, summarize=summarize)

    @mcp.tool()
    def knowledge_orphan_tickets(min_doc_similarity: float = 0.55, limit: int = 50) -> dict:
        """Find Jira issues with no matching documentation (knowledge gaps).

        Args:
            min_doc_similarity: Below this best-match similarity ⇒ "undocumented".
            limit:              Max issues to evaluate (cost guard).
        """
        from workflows.knowledge.tasks.cross_link import orphan_jira
        logger.info("Tool called: knowledge_orphan_tickets")
        return orphan_jira(min_doc_similarity=min_doc_similarity, limit=limit)

    @mcp.tool()
    def knowledge_stale_docs(min_code_similarity: float = 0.6, limit: int = 50) -> dict:
        """Find docs that closely match already-shipped (closed/merged) code —
        candidates to review for staleness against the implementation.

        Args:
            min_code_similarity: Similarity floor for a doc↔code match.
            limit:               Max doc pages to evaluate.
        """
        from workflows.knowledge.tasks.cross_link import stale_docs
        logger.info("Tool called: knowledge_stale_docs")
        return stale_docs(min_code_similarity=min_code_similarity, limit=limit)

    @mcp.tool()
    def knowledge_scan_watchlist(watchlist_id: str, k: int = 8) -> dict:
        """Run a watchlist (watchlists.yaml) and return ranked hit cards with
        why-relevant annotations. Omit/!mismatch the id to see available ids.

        Args:
            watchlist_id: e.g. 'payments-integration'.
            k:            Max cards (default 8).
        """
        from workflows.knowledge.tasks.topic_scan import topic_scan
        logger.info("Tool called: knowledge_scan_watchlist id=%s", watchlist_id)
        return topic_scan(watchlist_id, k=k)
