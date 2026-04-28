"""Grok Chat Completions API service.

xAI's API is OpenAI-compatible (POST /v1/chat/completions).

Built-in tools supported by Grok:
  - web_search     — live web search results injected into context
  - x_post_search  — search posts on X (Twitter)

Vision is supported by grok-2-vision-1212: pass image URLs as content
blocks with type 'image_url'.

See: https://docs.x.ai/api-reference
"""
from typing import Optional, List

from apps.grok.references.web.base_api_service import BaseApiServiceGrok, DEFAULT_MODEL
from apps.grok.references.dto.chat import (
    DtoGrokResponse,
    DtoGrokChoice,
    DtoGrokMessage,
    DtoGrokUsage,
)


class ApiServiceGrokChat(BaseApiServiceGrok):
    """Chat Completions service — text generation and tool-augmented responses."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def chat(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[dict]] = None,
        stream: bool = False,
    ) -> DtoGrokResponse:
        """Send a chat completions request to Grok.

        Pass messages as [{"role": "user"/"system"/"assistant", "content": "..."}].
        To use built-in tools pass xAI live_search format e.g.:
          tools=[{"type": "live_search", "live_search": {"sources": [{"type": "web"}]}}]
          tools=[{"type": "live_search", "live_search": {"sources": [{"type": "x"}]}}]
        """
        params: dict = {
            "model": model or self.default_model,
            "messages": messages,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        # xAI-specific tool types (e.g. live_search) are not part of the OpenAI
        # schema so the SDK strips their nested fields before serialisation.
        # Passing via extra_body sends the dict verbatim and bypasses validation.
        if tools:
            params["extra_body"] = {"tools": tools}

        response = self.native_client.chat.completions.create(**params)
        return self._map(response)

    def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> DtoGrokResponse:
        """Convenience wrapper — single user prompt with optional system message."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)

    def web_search(self, query: str, model: Optional[str] = None) -> DtoGrokResponse:
        """Ask Grok to answer using live web search results."""
        return self.chat(
            messages=[{"role": "user", "content": query}],
            model=model or self.default_model,
            tools=[{"type": "live_search", "live_search": {"sources": [{"type": "web"}]}}],
        )

    def x_search(self, query: str, model: Optional[str] = None) -> DtoGrokResponse:
        """Ask Grok to answer grounded in X (Twitter) posts."""
        return self.chat(
            messages=[{"role": "user", "content": query}],
            model=model or self.default_model,
            tools=[{"type": "live_search", "live_search": {"sources": [{"type": "x"}]}}],
        )

    def _map(self, response) -> DtoGrokResponse:
        usage = None
        raw_usage = getattr(response, "usage", None)
        if raw_usage:
            usage = DtoGrokUsage(
                prompt_tokens=getattr(raw_usage, "prompt_tokens", None),
                completion_tokens=getattr(raw_usage, "completion_tokens", None),
                total_tokens=getattr(raw_usage, "total_tokens", None),
                prompt_tokens_details=getattr(raw_usage, "prompt_tokens_details", None),
                completion_tokens_details=getattr(raw_usage, "completion_tokens_details", None),
            )

        choices = []
        for c in getattr(response, "choices", None) or []:
            msg = getattr(c, "message", None)
            choices.append(DtoGrokChoice(
                index=getattr(c, "index", None),
                finish_reason=getattr(c, "finish_reason", None),
                message=DtoGrokMessage(
                    role=getattr(msg, "role", None) if msg else None,
                    content=getattr(msg, "content", None) if msg else None,
                    tool_calls=getattr(msg, "tool_calls", None) if msg else None,
                ),
            ))

        output_text = None
        if choices and choices[0].message:
            output_text = choices[0].message.content

        return DtoGrokResponse(
            id=getattr(response, "id", None),
            object=getattr(response, "object", None),
            created=getattr(response, "created", None),
            model=getattr(response, "model", None),
            choices=choices,
            usage=usage,
            output_text=output_text,
        )
