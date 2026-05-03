"""MCP tools — high-level RAG over the local knowledge base.

Exposes the end-to-end answer pipeline as `knowledge_ask` so Claude Desktop
can call it directly without first computing an embedding by hand.
"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

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
