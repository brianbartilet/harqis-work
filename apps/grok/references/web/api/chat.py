"""Grok Chat Completions and Responses API service.

Standard chat uses the OpenAI-compatible POST /v1/chat/completions endpoint.

Search-grounded requests use POST /v1/responses with server-side tools:
  - tools: [{"type": "web_search"}]  — live web search
  - tools: [{"type": "x_search"}]    — X (Twitter) posts

Vision is supported by grok-2-vision-1212: pass image URLs as content
blocks with type 'image_url'.

See: https://docs.x.ai/api-reference
"""
import httpx
from typing import Optional, List

from apps.grok.references.web.base_api_service import BaseApiServiceGrok, DEFAULT_MODEL
from apps.grok.references.dto.chat import (
    DtoGrokResponse,
    DtoGrokChoice,
    DtoGrokMessage,
    DtoGrokUsage,
)

_XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"
_XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"
_SEARCH_MODEL = "grok-4"  # server-side tools require grok-4 family


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
    ) -> DtoGrokResponse:
        """Send a standard chat completions request (no tools) via the openai SDK."""
        params: dict = {
            "model": model or self.default_model,
            "messages": messages,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

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
        """Ask Grok to answer using live web search via the Responses API.

        Requires grok-4 family — defaults to grok-4 when no model is specified.
        """
        body = {
            "model": model or _SEARCH_MODEL,
            "input": query,
            "tools": [{"type": "web_search"}],
        }
        return self._raw_responses(body)

    def x_search(self, query: str, model: Optional[str] = None) -> DtoGrokResponse:
        """Ask Grok to answer grounded in X (Twitter) posts via the Responses API.

        Requires grok-4 family — defaults to grok-4 when no model is specified.
        """
        body = {
            "model": model or _SEARCH_MODEL,
            "input": query,
            "tools": [{"type": "x_search"}],
        }
        return self._raw_responses(body)

    def _raw_chat(self, body: dict) -> DtoGrokResponse:
        """POST to xAI chat completions via httpx, bypassing openai SDK validation."""
        resp = httpx.post(
            _XAI_CHAT_URL,
            headers={
                "Authorization": f"Bearer {self.native_client.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        if not resp.is_success:
            raise RuntimeError(
                f"xAI API {resp.status_code}: {resp.text}"
            )
        return self._map_dict(resp.json())

    def _raw_responses(self, body: dict) -> DtoGrokResponse:
        """POST to xAI /v1/responses endpoint (Agent Tools / search_parameters API)."""
        resp = httpx.post(
            _XAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self.native_client.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        if not resp.is_success:
            raise RuntimeError(
                f"xAI API {resp.status_code}: {resp.text}"
            )
        return self._map_responses_dict(resp.json())

    def _map(self, response) -> DtoGrokResponse:
        """Map an openai SDK response object to DtoGrokResponse."""
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
        output_text = choices[0].message.content if choices and choices[0].message else None
        return DtoGrokResponse(
            id=getattr(response, "id", None),
            object=getattr(response, "object", None),
            created=getattr(response, "created", None),
            model=getattr(response, "model", None),
            choices=choices,
            usage=usage,
            output_text=output_text,
        )

    def _map_responses_dict(self, data: dict) -> DtoGrokResponse:
        """Map a /v1/responses ModelResponse dict to DtoGrokResponse.

        The output array contains items of various types; the assistant text lives
        in items with type=='message', inside a content block with type=='output_text'.
        """
        output_text = None
        for item in data.get("output") or []:
            if item.get("type") == "message":
                for block in item.get("content") or []:
                    if block.get("type") == "output_text":
                        output_text = block.get("text")
                        break
            if output_text is not None:
                break

        raw_usage = data.get("usage") or {}
        usage = DtoGrokUsage(
            prompt_tokens=raw_usage.get("input_tokens"),
            completion_tokens=raw_usage.get("output_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
        ) if raw_usage else None

        return DtoGrokResponse(
            id=data.get("id"),
            object=data.get("object"),
            created=data.get("created_at"),
            model=data.get("model"),
            choices=[],
            usage=usage,
            output_text=output_text,
        )

    def _map_dict(self, data: dict) -> DtoGrokResponse:
        """Map a raw API response dict to DtoGrokResponse."""
        raw_usage = data.get("usage") or {}
        usage = DtoGrokUsage(
            prompt_tokens=raw_usage.get("prompt_tokens"),
            completion_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
        ) if raw_usage else None

        choices = []
        for c in data.get("choices") or []:
            msg = c.get("message") or {}
            choices.append(DtoGrokChoice(
                index=c.get("index"),
                finish_reason=c.get("finish_reason"),
                message=DtoGrokMessage(
                    role=msg.get("role"),
                    content=msg.get("content"),
                    tool_calls=msg.get("tool_calls"),
                ),
            ))

        output_text = choices[0].message.content if choices and choices[0].message else None
        return DtoGrokResponse(
            id=data.get("id"),
            object=data.get("object"),
            created=data.get("created"),
            model=data.get("model"),
            choices=choices,
            usage=usage,
            output_text=output_text,
        )
