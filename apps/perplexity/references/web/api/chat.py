"""Perplexity Sonar Chat Completions service.

Sonar is OpenAI-compatible: standard chat with messages array, plus Perplexity-specific
extensions like web search, domain filtering, recency filtering, and inline citations.

Models: sonar, sonar-pro, sonar-reasoning, sonar-deep-research

See: https://docs.perplexity.ai/docs/sonar
"""
from typing import Optional, List

from apps.perplexity.references.web.base_api_service import BaseApiServicePerplexity
from apps.perplexity.references.dto.chat import (
    DtoPerplexityChatResponse,
    DtoPerplexityChoice,
    DtoPerplexityMessage,
    DtoPerplexityUsage,
)


class ApiServicePerplexityChat(BaseApiServicePerplexity):
    """Perplexity Sonar — chat completions with built-in web search and citations."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def chat(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        search_domain_filter: Optional[List[str]] = None,
        search_recency_filter: Optional[str] = None,
    ) -> DtoPerplexityChatResponse:
        """Send a chat completion request to Sonar.

        Args:
            messages:              OpenAI-style list of {role, content} dicts.
            model:                 Model id. Defaults to config.app_data['model'] or 'sonar'.
            temperature:           Sampling temperature (0.0–2.0).
            max_tokens:            Maximum tokens in the response.
            search_domain_filter:  Optional list of domain names to restrict (or exclude with '-' prefix) web search to.
            search_recency_filter: Recency filter: 'month', 'week', 'day', or 'hour'.
        """
        body: dict = {
            "model": model or self.default_model,
            "messages": messages,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if search_domain_filter:
            body["search_domain_filter"] = search_domain_filter
        if search_recency_filter:
            body["search_recency_filter"] = search_recency_filter

        data = self._post("/chat/completions", body)
        return self._map(data)

    def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        search_domain_filter: Optional[List[str]] = None,
        search_recency_filter: Optional[str] = None,
    ) -> DtoPerplexityChatResponse:
        """Convenience wrapper: single user prompt with optional system message."""
        messages: List[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            search_domain_filter=search_domain_filter,
            search_recency_filter=search_recency_filter,
        )

    def submit_async(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """Submit an asynchronous chat completion request.

        Returns the request envelope including the request id, which can later be
        retrieved via `get_async`. Useful for sonar-deep-research jobs that may
        take several minutes.
        """
        body: dict = {
            "request": {
                "model": model or self.default_model,
                "messages": messages,
            }
        }
        if max_tokens is not None:
            body["request"]["max_tokens"] = max_tokens
        return self._post("/async/chat/completions", body)

    def list_async(self) -> dict:
        """List all asynchronous chat completion requests for the account."""
        return self._get("/async/chat/completions")

    def get_async(self, request_id: str) -> dict:
        """Retrieve the response for a previously submitted async request."""
        return self._get(f"/async/chat/completions/{request_id}")

    def _map(self, data: dict) -> DtoPerplexityChatResponse:
        raw_usage = data.get("usage") or {}
        usage = DtoPerplexityUsage(
            prompt_tokens=raw_usage.get("prompt_tokens"),
            completion_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            citation_tokens=raw_usage.get("citation_tokens"),
            num_search_queries=raw_usage.get("num_search_queries"),
        ) if raw_usage else None

        choices = []
        for c in data.get("choices") or []:
            msg = c.get("message") or {}
            choices.append(DtoPerplexityChoice(
                index=c.get("index"),
                finish_reason=c.get("finish_reason"),
                message=DtoPerplexityMessage(
                    role=msg.get("role"),
                    content=msg.get("content"),
                ),
            ))

        output_text = choices[0].message.content if choices and choices[0].message else None
        return DtoPerplexityChatResponse(
            id=data.get("id"),
            object=data.get("object"),
            created=data.get("created"),
            model=data.get("model"),
            choices=choices,
            usage=usage,
            citations=data.get("citations") or [],
            output_text=output_text,
        )
