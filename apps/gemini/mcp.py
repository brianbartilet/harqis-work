import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.gemini.config import CONFIG
from apps.gemini.references.web.api.models import ApiServiceGeminiModels
from apps.gemini.references.web.api.generate import ApiServiceGeminiGenerate, DEFAULT_MODEL
from apps.gemini.references.web.api.embed import ApiServiceGeminiEmbed, DEFAULT_EMBED_MODEL

logger = logging.getLogger("harqis-mcp.gemini")


def register_gemini_tools(mcp: FastMCP):

    @mcp.tool()
    def list_gemini_models(page_size: int = 50) -> list[dict]:
        """List all Google Gemini models available to the configured API key.

        Args:
            page_size: Maximum number of models to return (default 50).
        """
        logger.info("Tool called: list_gemini_models")
        result = ApiServiceGeminiModels(CONFIG).list_models(page_size=page_size)
        models = result.get('models', []) if isinstance(result, dict) else []
        logger.info("list_gemini_models returned %d model(s)", len(models))
        return models

    @mcp.tool()
    def get_gemini_model(model_name: str) -> dict:
        """Get metadata for a specific Gemini model.

        Args:
            model_name: Full resource name, e.g. 'models/gemini-2.0-flash'.
        """
        logger.info("Tool called: get_gemini_model model_name=%s", model_name)
        result = ApiServiceGeminiModels(CONFIG).get_model(model_name)
        return result.__dict__ if hasattr(result, '__dict__') else (result if isinstance(result, dict) else {})

    @mcp.tool()
    def gemini_generate_content(
        prompt: str,
        model: str = DEFAULT_MODEL,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        system_instruction: Optional[str] = None,
    ) -> dict:
        """Generate text from a prompt using Google Gemini.

        Args:
            prompt:             The user text prompt to send to Gemini.
            model:              Model resource name (default 'models/gemini-2.0-flash').
            temperature:        Sampling temperature 0.0–2.0. Lower = more deterministic.
            max_output_tokens:  Maximum number of tokens in the response.
            system_instruction: Optional system-level instruction for the model.

        Returns:
            Dict with candidates list, each containing the generated text and finish reason.
        """
        logger.info("Tool called: gemini_generate_content model=%s prompt_len=%d", model, len(prompt))
        result = ApiServiceGeminiGenerate(CONFIG).generate_content(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system_instruction,
        )
        if hasattr(result, '__dict__'):
            data = result.__dict__
            logger.info(
                "gemini_generate_content finish_reason=%s total_tokens=%s",
                data.get('candidates', [{}])[0].get('finish_reason') if data.get('candidates') else None,
                data.get('usage_metadata', {}).get('total_token_count') if data.get('usage_metadata') else None,
            )
            return data
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def gemini_count_tokens(prompt: str, model: str = DEFAULT_MODEL) -> dict:
        """Count how many tokens a prompt would consume without generating a response.

        Args:
            prompt: The text prompt to tokenize.
            model:  Model resource name (default 'models/gemini-2.0-flash').

        Returns:
            Dict with totalTokens count.
        """
        logger.info("Tool called: gemini_count_tokens model=%s", model)
        result = ApiServiceGeminiGenerate(CONFIG).count_tokens(prompt=prompt, model=model)
        out = result.__dict__ if hasattr(result, '__dict__') else (result if isinstance(result, dict) else {})
        logger.info("gemini_count_tokens total_tokens=%s", out.get('total_tokens'))
        return out

    @mcp.tool()
    def gemini_embed_content(
        text: str,
        model: str = DEFAULT_EMBED_MODEL,
        task_type: Optional[str] = None,
    ) -> dict:
        """Generate a vector embedding for a text string using Gemini.

        Args:
            text:      The text to embed.
            model:     Embedding model name (default 'models/text-embedding-004').
            task_type: Optional task hint — e.g. 'RETRIEVAL_DOCUMENT',
                       'RETRIEVAL_QUERY', 'SEMANTIC_SIMILARITY', 'CLASSIFICATION'.
        """
        logger.info("Tool called: gemini_embed_content model=%s text_len=%d", model, len(text))
        result = ApiServiceGeminiEmbed(CONFIG).embed_content(text=text, model=model, task_type=task_type)
        out = result.__dict__ if hasattr(result, '__dict__') else (result if isinstance(result, dict) else {})
        embedding = out.get('embedding')
        dims = len(embedding.values) if embedding and hasattr(embedding, 'values') else 0
        logger.info("gemini_embed_content embedding_dims=%d", dims)
        return out

    @mcp.tool()
    def gemini_batch_embed_contents(
        texts: list[str],
        model: str = DEFAULT_EMBED_MODEL,
        task_type: Optional[str] = None,
    ) -> dict:
        """Generate vector embeddings for multiple texts in a single Gemini API call.

        Args:
            texts:     List of text strings to embed.
            model:     Embedding model name (default 'models/text-embedding-004').
            task_type: Optional task hint applied to all requests.

        Returns:
            Dict with embeddings list, each containing a values list of floats.
        """
        logger.info("Tool called: gemini_batch_embed_contents count=%d model=%s", len(texts), model)
        result = ApiServiceGeminiEmbed(CONFIG).batch_embed_contents(texts=texts, model=model, task_type=task_type)
        out = result.__dict__ if hasattr(result, '__dict__') else (result if isinstance(result, dict) else {})
        logger.info("gemini_batch_embed_contents returned %d embedding(s)", len(out.get('embeddings', [])))
        return out
