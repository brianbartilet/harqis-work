import os
import time
import random
import asyncio

import httpx
from anthropic import AsyncAnthropic, Anthropic
from anthropic import RateLimitError, APIConnectionError, InternalServerError

from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.utilities.logging.custom_logger import logger as log

from typing import TypeVar, Any, Callable, Optional
TWebService = TypeVar("TWebService")

_RETRYABLE = (RateLimitError, APIConnectionError, InternalServerError)
_HTTPX_RETRYABLE_STATUSES = {429, 500, 503, 529}


class BaseApiServiceAnthropic(BaseFixtureServiceRest):
    """
    Base service for interacting with Anthropic Claude API.

    This class provides both synchronous and asynchronous interfaces for sending
    prompts to Claude models using the official Anthropic Python SDK.

    It is designed to integrate with REST-style service abstractions while allowing
    flexibility in execution mode.

    Rate limit / backoff config keys (under app_data):
        max_retries (int):       Maximum retry attempts on rate-limit or transient errors. Default 3.
        retry_base_delay (float): Base delay in seconds for exponential backoff. Default 1.0.
        retry_max_delay (float):  Cap on backoff delay in seconds. Default 60.0.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"
    DEFAULT_MAX_TOKENS = 1024
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_BASE_DELAY = 1.0
    DEFAULT_RETRY_MAX_DELAY = 60.0

    def __init__(
        self,
        config: Any,
        use_base_client: bool = True,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.use_base_client = use_base_client
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        self.model = config.app_data.get('model', self.DEFAULT_MODEL)
        self.max_tokens = config.app_data.get('max_tokens', self.DEFAULT_MAX_TOKENS)
        self.max_retries = int(config.app_data.get('max_retries', self.DEFAULT_MAX_RETRIES))
        self.retry_base_delay = float(config.app_data.get('retry_base_delay', self.DEFAULT_RETRY_BASE_DELAY))
        self.retry_max_delay = float(config.app_data.get('retry_max_delay', self.DEFAULT_RETRY_MAX_DELAY))

        self.base_client: Optional[Anthropic] = None
        self.async_client: Optional[AsyncAnthropic] = None

        if self.use_base_client:
            self.base_client = Anthropic(api_key=self.api_key, max_retries=0)
            self.async_client = AsyncAnthropic(api_key=self.api_key, max_retries=0)
        else:
            super(BaseApiServiceAnthropic, self).__init__(config, **kwargs)

    # region Backoff helpers

    def _with_backoff(self, fn: Callable, *args, **kwargs):
        """
        Execute a synchronous callable with exponential backoff on retryable errors.

        Retries on: RateLimitError, APIConnectionError, InternalServerError.
        Uses jittered exponential backoff capped at retry_max_delay.
        """
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                delay = min(
                    self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                    self.retry_max_delay,
                )
                log.warning(
                    f"Anthropic retryable error [{type(exc).__name__}] "
                    f"attempt {attempt + 1}/{self.max_retries} — retrying in {delay:.1f}s: {exc}"
                )
                time.sleep(delay)
        raise last_exc

    async def _with_backoff_async(self, fn: Callable, *args, **kwargs):
        """
        Execute an async callable with exponential backoff on retryable errors.
        """
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                delay = min(
                    self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                    self.retry_max_delay,
                )
                log.warning(
                    f"Anthropic retryable error [{type(exc).__name__}] "
                    f"attempt {attempt + 1}/{self.max_retries} — retrying in {delay:.1f}s: {exc}"
                )
                await asyncio.sleep(delay)
        raise last_exc

    def _httpx_with_backoff(self, fn: Callable, *args, **kwargs) -> httpx.Response:
        """
        Execute a synchronous httpx call with exponential backoff.

        Retries on HTTP 429 (rate limit), 500, 503, 529 (overloaded), and
        httpx connection/timeout errors. Raises on any other status after
        calling raise_for_status().
        """
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                response: httpx.Response = fn(*args, **kwargs)
                if response.status_code in _HTTPX_RETRYABLE_STATUSES:
                    exc = httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    last_exc = exc
                    if attempt == self.max_retries:
                        break
                    delay = min(
                        self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                        self.retry_max_delay,
                    )
                    log.warning(
                        f"Anthropic HTTP {response.status_code} "
                        f"attempt {attempt + 1}/{self.max_retries} — retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                delay = min(
                    self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                    self.retry_max_delay,
                )
                log.warning(
                    f"Anthropic connection error [{type(exc).__name__}] "
                    f"attempt {attempt + 1}/{self.max_retries} — retrying in {delay:.1f}s: {exc}"
                )
                time.sleep(delay)
        raise last_exc

    # endregion

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
        Retries automatically on rate-limit and transient errors.

        Use this when:
            - Running tests (pytest / Gherkin)
            - Sequential workflows
            - Simplicity is preferred over performance

        Args:
            prompt:     The user input text sent to Claude.
            model:      Optional override of model name.
            max_tokens: Optional override for max tokens.
            system:     Optional system prompt for instruction context.

        Returns:
            Response object from Anthropic SDK.

        Raises:
            RuntimeError: If the sync client is not initialized.
        """
        if not self.base_client:
            raise RuntimeError("Anthropic sync client is not initialized.")

        payload = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        return self._with_backoff(self.base_client.messages.create, **payload)

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
        Retries automatically on rate-limit and transient errors.

        Use this when:
            - Sending multiple requests in parallel
            - Building high-performance services
            - Using async frameworks (FastAPI, asyncio workers)

        Example:
            await service.send_message_async("Hello")

        Args:
            prompt:     The user input text sent to Claude.
            model:      Optional override of model name.
            max_tokens: Optional override for max tokens.
            system:     Optional system prompt for instruction context.

        Returns:
            Response object from Anthropic SDK.

        Raises:
            RuntimeError: If the async client is not initialized.
        """
        if not self.async_client:
            raise RuntimeError("Anthropic async client is not initialized.")

        payload = {
            "model": model or self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        return await self._with_backoff_async(self.async_client.messages.create, **payload)

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
            prompt: The user input text.
            model:  Optional model override.

        Returns:
            Token count response object.

        Raises:
            RuntimeError: If the sync client is not initialized.
        """
        if not self.base_client:
            raise RuntimeError("Anthropic sync client is not initialized.")

        return self._with_backoff(
            self.base_client.messages.count_tokens,
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}],
        )
