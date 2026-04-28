import logging
from typing import Optional, List

from mcp.server.fastmcp import FastMCP
from apps.grok.config import CONFIG
from apps.grok.references.web.api.chat import ApiServiceGrokChat
from apps.grok.references.web.api.models import ApiServiceGrokModels
from apps.grok.references.web.api.embeddings import ApiServiceGrokEmbeddings
from apps.grok.references.web.base_api_service import DEFAULT_MODEL, EMBEDDING_MODEL

logger = logging.getLogger("harqis-mcp.grok")


def register_grok_tools(mcp: FastMCP):

    @mcp.tool()
    def grok_chat(
        prompt: str,
        model: str = DEFAULT_MODEL,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """Generate a text response using xAI Grok.

        Args:
            prompt:      The user message / question.
            model:       Grok model ID (default: grok-4).
            system:      Optional system-level instructions.
            temperature: Sampling temperature 0.0–2.0.
            max_tokens:  Maximum tokens in the response.
        """
        logger.info("Tool called: grok_chat model=%s prompt_len=%d", model, len(prompt))
        svc = ApiServiceGrokChat(CONFIG)
        result = svc.complete(prompt=prompt, model=model, system=system,
                              temperature=temperature, max_tokens=max_tokens)
        out = {
            "id": result.id,
            "model": result.model,
            "output_text": result.output_text,
            "finish_reason": result.choices[0].finish_reason if result.choices else None,
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("grok_chat id=%s finish=%s", result.id, out["finish_reason"])
        return out

    @mcp.tool()
    def grok_web_search(
        query: str,
        model: str = DEFAULT_MODEL,
    ) -> dict:
        """Ask Grok to answer a query using live web search results.

        Grok fetches real-time information from the web and incorporates it
        into the response — useful for current events, recent data, or
        anything beyond the model's training cutoff.

        Args:
            query: The question or search query.
            model: Grok model ID (default: grok-4).
        """
        logger.info("Tool called: grok_web_search model=%s query_len=%d", model, len(query))
        svc = ApiServiceGrokChat(CONFIG)
        result = svc.web_search(query=query, model=model)
        out = {
            "id": result.id,
            "model": result.model,
            "output_text": result.output_text,
            "finish_reason": result.choices[0].finish_reason if result.choices else None,
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("grok_web_search id=%s", result.id)
        return out

    @mcp.tool()
    def grok_x_search(
        query: str,
        model: str = DEFAULT_MODEL,
    ) -> dict:
        """Ask Grok to answer a query using X (Twitter) post search.

        Grok searches posts on X and synthesizes an answer — useful for
        trending topics, community sentiment, and real-time social context.

        Args:
            query: The question or topic to search on X.
            model: Grok model ID (default: grok-4).
        """
        logger.info("Tool called: grok_x_search model=%s query_len=%d", model, len(query))
        svc = ApiServiceGrokChat(CONFIG)
        result = svc.x_search(query=query, model=model)
        out = {
            "id": result.id,
            "model": result.model,
            "output_text": result.output_text,
            "finish_reason": result.choices[0].finish_reason if result.choices else None,
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("grok_x_search id=%s", result.id)
        return out

    @mcp.tool()
    def grok_list_models() -> list:
        """List all Grok models available to the authenticated account."""
        logger.info("Tool called: grok_list_models")
        svc = ApiServiceGrokModels(CONFIG)
        result = svc.list_models()
        result = result if isinstance(result, list) else []
        logger.info("grok_list_models returned %d model(s)", len(result))
        return [m.__dict__ for m in result]

    @mcp.tool()
    def grok_embed(
        text: str,
        model: str = EMBEDDING_MODEL,
    ) -> dict:
        """Generate a text embedding vector using Grok.

        Returns a 4096-dimensional float vector for the input text.
        Useful for semantic search, clustering, and similarity tasks.
        Requires embedding model access (grok-3-embedding-exp) on the xAI account.

        Args:
            text:  The text to embed.
            model: Embedding model (default: grok-3-embedding-exp).
        """
        logger.info("Tool called: grok_embed model=%s text_len=%d", model, len(text))
        svc = ApiServiceGrokEmbeddings(CONFIG)
        result = svc.embed(input=text, model=model)
        first = result.data[0] if result.data else None
        out = {
            "model": result.model,
            "embedding_dims": len(first.embedding) if first and first.embedding else 0,
            "embedding": first.embedding if first else [],
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("grok_embed dims=%d", out["embedding_dims"])
        return out
