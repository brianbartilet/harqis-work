import os
from anthropic import AsyncAnthropic
from anthropic import Anthropic

from core.web.services.fixtures.rest import BaseFixtureServiceRest

from typing import TypeVar, Any, Optional
TWebService = TypeVar("TWebService")


class BaseApiServiceAnthropic(BaseFixtureServiceRest):
    """
    Base service for interacting with Anthropic Claude API.

    This class provides both synchronous and asynchronous interfaces for sending
    prompts to Claude models using the official Anthropic Python SDK.

    It is designed to integrate with REST-style service abstractions while allowing
    flexibility in execution mode
    """

    DEFAULT_MODEL = "claude-opus-4-6"
    DEFAULT_MAX_TOKENS = 1024

    def __init__(
        self,
        config: Any,
        use_base_client: bool = True,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Anthropic API service.

        Args:
            config:
                Configuration object passed from framework.
            use_base_client:
                Whether to initialize Anthropic SDK clients.
            api_key:
                Optional API key override. Defaults to ANTHROPIC_API_KEY env.
            model:
                Default Claude model to use.
            max_tokens:
                Default max tokens for responses.
            **kwargs:
                Additional arguments passed to parent class.

        Returns:
            None
        """

        self.use_base_client = use_base_client
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        self.model = config.app_data.get('model', self.DEFAULT_MODEL)
        self.max_tokens = config.app_data.get('max_tokens', self.DEFAULT_MAX_TOKENS)

        self.base_client: Optional[Anthropic] = None
        self.async_client: Optional[AsyncAnthropic] = None

        if self.use_base_client:
            self.base_client = Anthropic(api_key=self.api_key)
            self.async_client = AsyncAnthropic(api_key=self.api_key)
        else:
            super(BaseApiServiceAnthropic, self).__init__(config, **kwargs)

    def send_message(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
    ):
        """
        Send a message to Claude using the synchronous client.

        This method BLOCKS execution until a response is returned.

        Use this when:
            - Running tests (pytest / Gherkin)
            - Sequential workflows
            - Simplicity is preferred over performance

        Args:
            prompt:
                The user input text sent to Claude.
            model:
                Optional override of model name.
            max_tokens:
                Optional override for max tokens.
            system:
                Optional system prompt for instruction context.

        Returns:
            Response object from Anthropic SDK.

        Raises:
            RuntimeError:
                If the sync client is not initialized.
        """
        if not self.base_client:
            raise RuntimeError("Anthropic sync client is not initialized.")

        payload = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }

        if system:
            payload["system"] = system

        return self.base_client.messages.create(**payload)

    async def send_message_async(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
    ):
        """
        Send a message to Claude using the asynchronous client.

        This method is NON-BLOCKING and must be awaited.

        Use this when:
            - Sending multiple requests in parallel
            - Building high-performance services
            - Using async frameworks (FastAPI, asyncio workers)

        Example:
            await service.send_message_async("Hello")

        Args:
            prompt:
                The user input text sent to Claude.
            model:
                Optional override of model name.
            max_tokens:
                Optional override for max tokens.
            system:
                Optional system prompt for instruction context.

        Returns:
            Response object from Anthropic SDK.

        Raises:
            RuntimeError:
                If the async client is not initialized.
        """
        if not self.async_client:
            raise RuntimeError("Anthropic async client is not initialized.")

        payload = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }

        if system:
            payload["system"] = system

        return await self.async_client.messages.create(**payload)

    def count_tokens(
        self,
        prompt: str,
        model: Optional[str] = None,
    ):
        """
        Count tokens for a given input before sending to Claude.

        Useful for:
            - Cost estimation
            - Token limit validation
            - Prompt optimization

        Args:
            prompt:
                The user input text.
            model:
                Optional model override.

        Returns:
            Token count response object.

        Raises:
            RuntimeError:
                If the sync client is not initialized.
        """
        if not self.base_client:
            raise RuntimeError("Anthropic sync client is not initialized.")

        return self.base_client.messages.count_tokens(
            model=model or self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )




