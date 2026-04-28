"""Perplexity AI MCP tools — Sonar chat with web search, search, embeddings."""
import logging
from typing import Optional, List

from mcp.server.fastmcp import FastMCP
from apps.perplexity.config import CONFIG
from apps.perplexity.references.web.api.chat import ApiServicePerplexityChat
from apps.perplexity.references.web.api.search import ApiServicePerplexitySearch
from apps.perplexity.references.web.api.embeddings import ApiServicePerplexityEmbeddings
from apps.perplexity.references.web.api.models import ApiServicePerplexityModels
from apps.perplexity.references.web.base_api_service import DEFAULT_MODEL, EMBEDDING_MODEL

logger = logging.getLogger("harqis-mcp.perplexity")


def register_perplexity_tools(mcp: FastMCP):

    @mcp.tool()
    def perplexity_chat(
        prompt: str,
        model: str = DEFAULT_MODEL,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        search_domain_filter: Optional[List[str]] = None,
        search_recency_filter: Optional[str] = None,
    ) -> dict:
        """Generate a Perplexity Sonar response with built-in live web search.

        Sonar grounds every answer in real-time web results and returns inline citations.
        Use the search_* filters to constrain which sources are used.

        Args:
            prompt:                The user message / question.
            model:                 Sonar model: 'sonar', 'sonar-pro', 'sonar-reasoning',
                                   'sonar-deep-research'. Default: sonar.
            system:                Optional system-level instructions.
            temperature:           Sampling temperature 0.0–2.0.
            max_tokens:            Maximum tokens in the response.
            search_domain_filter:  List of domains to restrict to, e.g.
                                   ['nytimes.com', 'wikipedia.org']. Prefix with '-'
                                   to exclude (e.g. '-pinterest.com').
            search_recency_filter: 'month', 'week', 'day', or 'hour'.
        """
        logger.info("Tool called: perplexity_chat model=%s prompt_len=%d", model, len(prompt))
        svc = ApiServicePerplexityChat(CONFIG)
        result = svc.complete(
            prompt=prompt, model=model, system=system,
            temperature=temperature, max_tokens=max_tokens,
            search_domain_filter=search_domain_filter,
            search_recency_filter=search_recency_filter,
        )
        out = {
            "id": result.id,
            "model": result.model,
            "output_text": result.output_text,
            "citations": result.citations or [],
            "finish_reason": result.choices[0].finish_reason if result.choices else None,
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("perplexity_chat id=%s citations=%d", result.id, len(out["citations"]))
        return out

    @mcp.tool()
    def perplexity_submit_async(
        prompt: str,
        model: str = "sonar-deep-research",
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """Submit a long-running Perplexity request asynchronously.

        Use this for sonar-deep-research jobs that may take several minutes.
        Retrieve the result later with perplexity_get_async(request_id).

        Args:
            prompt:     The user query.
            model:      Async-friendly model. Default: sonar-deep-research.
            system:     Optional system instructions.
            max_tokens: Maximum tokens in the eventual response.
        """
        logger.info("Tool called: perplexity_submit_async model=%s", model)
        messages: list = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        svc = ApiServicePerplexityChat(CONFIG)
        result = svc.submit_async(messages=messages, model=model, max_tokens=max_tokens)
        result = result if isinstance(result, dict) else {}
        logger.info("perplexity_submit_async id=%s", result.get("id"))
        return result

    @mcp.tool()
    def perplexity_get_async(request_id: str) -> dict:
        """Retrieve the result of a previously submitted async Perplexity request.

        Args:
            request_id: The request id returned by perplexity_submit_async.
        """
        logger.info("Tool called: perplexity_get_async id=%s", request_id)
        svc = ApiServicePerplexityChat(CONFIG)
        result = svc.get_async(request_id=request_id)
        result = result if isinstance(result, dict) else {}
        logger.info("perplexity_get_async status=%s", result.get("status"))
        return result

    @mcp.tool()
    def perplexity_list_async() -> dict:
        """List all asynchronous Perplexity chat requests for the account."""
        logger.info("Tool called: perplexity_list_async")
        svc = ApiServicePerplexityChat(CONFIG)
        result = svc.list_async()
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def perplexity_search(
        query: str,
        max_results: Optional[int] = None,
        search_domain_filter: Optional[List[str]] = None,
        search_recency_filter: Optional[str] = None,
        language: Optional[str] = None,
    ) -> dict:
        """Run a direct Perplexity web search and return ranked URL results.

        Unlike perplexity_chat, this returns raw search results (title + url + snippet)
        with no LLM synthesis — useful when you need links to feed into another step.

        Args:
            query:                 The search query string.
            max_results:           Maximum number of results to return.
            search_domain_filter:  Domain whitelist (or '-domain' blacklist).
            search_recency_filter: 'month', 'week', 'day', or 'hour'.
            language:              ISO language code, e.g. 'en'.
        """
        logger.info("Tool called: perplexity_search query_len=%d", len(query))
        svc = ApiServicePerplexitySearch(CONFIG)
        result = svc.search(
            query=query,
            max_results=max_results,
            search_domain_filter=search_domain_filter,
            search_recency_filter=search_recency_filter,
            language=language,
        )
        out = {
            "query": result.query,
            "results": [r.__dict__ for r in (result.results or [])],
            "count": len(result.results or []),
        }
        logger.info("perplexity_search returned %d result(s)", out["count"])
        return out

    @mcp.tool()
    def perplexity_embed(text: str, model: str = EMBEDDING_MODEL) -> dict:
        """Generate an embedding vector for a piece of text.

        Args:
            text:  The text to embed.
            model: Embedding model id (default: sonar-embed).
        """
        logger.info("Tool called: perplexity_embed model=%s text_len=%d", model, len(text))
        svc = ApiServicePerplexityEmbeddings(CONFIG)
        result = svc.embed(input=text, model=model)
        first = result.data[0] if result.data else None
        out = {
            "model": result.model,
            "embedding_dims": len(first.embedding) if first and first.embedding else 0,
            "embedding": first.embedding if first else [],
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("perplexity_embed dims=%d", out["embedding_dims"])
        return out

    @mcp.tool()
    def perplexity_list_models() -> list:
        """List all Perplexity models available to the authenticated account."""
        logger.info("Tool called: perplexity_list_models")
        svc = ApiServicePerplexityModels(CONFIG)
        result = svc.list_models()
        result = result if isinstance(result, list) else []
        logger.info("perplexity_list_models returned %d model(s)", len(result))
        return [m.__dict__ for m in result]
