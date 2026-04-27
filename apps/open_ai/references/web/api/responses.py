"""OpenAI Responses API service.

The Responses API (POST /v1/responses) is the current recommended interface for
text generation, multi-turn conversations, and built-in tool use. It supersedes
Chat Completions for agentic workflows and supports stateful response chaining
via previous_response_id.

Built-in tools supported:
  - code_interpreter  — sandboxed Python execution
  - web_search_preview — live web search
  - file_search        — search over uploaded vector store files

See: https://platform.openai.com/docs/api-reference/responses
"""
from typing import Optional, List

from apps.open_ai.references.web.base_api_service import BaseApiServiceOpenAi
from apps.open_ai.references.dto.response import (
    DtoOpenAiResponse,
    DtoOpenAiOutputItem,
    DtoOpenAiUsage,
)

DEFAULT_MODEL = "gpt-4.1"


class ApiServiceOpenAiResponses(BaseApiServiceOpenAi):
    """Responses API — create, retrieve, and delete stored responses."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def create_response(
        self,
        input: str | List[dict],
        model: Optional[str] = None,
        instructions: Optional[str] = None,
        tools: Optional[List[dict]] = None,
        previous_response_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        stream: bool = False,
        store: bool = True,
        metadata: Optional[dict] = None,
    ) -> DtoOpenAiResponse:
        """Create a response via the Responses API.

        For multi-turn conversations pass previous_response_id to continue
        a prior session without re-sending history.

        To enable built-in tools pass e.g.:
          tools=[{"type": "web_search_preview"}]
          tools=[{"type": "code_interpreter", "container": {"type": "auto"}}]
          tools=[{"type": "file_search", "vector_store_ids": ["vs_..."]}]
        """
        params: dict = {
            "model": model or self.default_model,
            "input": input,
            "store": store,
        }
        if instructions is not None:
            params["instructions"] = instructions
        if tools:
            params["tools"] = tools
        if previous_response_id is not None:
            params["previous_response_id"] = previous_response_id
        if temperature is not None:
            params["temperature"] = temperature
        if max_output_tokens is not None:
            params["max_output_tokens"] = max_output_tokens
        if metadata:
            params["metadata"] = metadata

        response = self.native_client.responses.create(**params)
        return self._map_response(response)

    def get_response(self, response_id: str) -> DtoOpenAiResponse:
        """Retrieve a stored response by ID."""
        response = self.native_client.responses.retrieve(response_id)
        return self._map_response(response)

    def delete_response(self, response_id: str) -> dict:
        """Delete a stored response. Returns {"id": ..., "deleted": True}."""
        self.native_client.responses.delete(response_id)
        return {"id": response_id, "deleted": True}

    def list_input_items(self, response_id: str) -> List[dict]:
        """List the input items that were sent with a stored response."""
        page = self.native_client.responses.input_items.list(response_id)
        items = getattr(page, "data", []) or []
        return [
            item.model_dump() if hasattr(item, "model_dump") else vars(item)
            for item in items
        ]

    def _map_response(self, response) -> DtoOpenAiResponse:
        usage = None
        raw_usage = getattr(response, "usage", None)
        if raw_usage:
            usage = DtoOpenAiUsage(
                input_tokens=getattr(raw_usage, "input_tokens", None),
                output_tokens=getattr(raw_usage, "output_tokens", None),
                total_tokens=getattr(raw_usage, "total_tokens", None),
                input_tokens_details=getattr(raw_usage, "input_tokens_details", None),
                output_tokens_details=getattr(raw_usage, "output_tokens_details", None),
            )

        output_items: List[DtoOpenAiOutputItem] = []
        for item in getattr(response, "output", None) or []:
            output_items.append(DtoOpenAiOutputItem(
                id=getattr(item, "id", None),
                type=getattr(item, "type", None),
                status=getattr(item, "status", None),
                role=getattr(item, "role", None),
                content=getattr(item, "content", None),
                code=getattr(item, "code", None),
                outputs=getattr(item, "outputs", None),
            ))

        return DtoOpenAiResponse(
            id=getattr(response, "id", None),
            object=getattr(response, "object", None),
            created_at=getattr(response, "created_at", None),
            model=getattr(response, "model", None),
            status=getattr(response, "status", None),
            output=output_items,
            output_text=getattr(response, "output_text", None),
            usage=usage,
            error=getattr(response, "error", None),
            metadata=getattr(response, "metadata", None),
            previous_response_id=getattr(response, "previous_response_id", None),
        )
