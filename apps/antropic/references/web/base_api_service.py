import os
import time
import random
import asyncio

import httpx
from anthropic import AsyncAnthropic, Anthropic
from anthropic import APIStatusError, RateLimitError, APIConnectionError, InternalServerError

from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.utilities.logging.custom_logger import logger as log

from apps.antropic.provider import (
    PROVIDER_CLAUDE_CODE,
    ProviderConfig,
    ProviderResolutionError,
    detect_provider,
    scrub_competing_env,
)

from typing import TypeVar, Any, Callable, Optional
TWebService = TypeVar("TWebService")

_RETRYABLE = (RateLimitError, APIConnectionError, InternalServerError,
              httpx.RemoteProtocolError, httpx.ConnectError, httpx.TimeoutException)
_HTTPX_RETRYABLE_STATUSES = {413, 429, 500, 503, 529}

# Substrings (lowercased) that flag a 400-class error as actually a Max/API
# quota hit rather than a transient bad-request. Used to decide whether the
# fallback swap kicks in for this call.
_USAGE_LIMIT_PATTERNS = (
    "usage limit",
    "credit balance",
    "monthly spend limit",
    "quota",
)


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

        # Resolve the auth route. Precedence:
        #   1. Explicit ``api_key`` arg (caller knows what they want) →
        #      classic api-key auth, no detection.
        #   2. ``apps.antropic.provider.detect_provider()`` → Max bearer or
        #      api-key from env, with optional Max → API fallback wired in
        #      when both creds are present.
        # ``provider_config`` is exposed so callers / tests can introspect
        # the chosen path. ``self.api_key`` is preserved for back-compat with
        # subclasses that read it directly (e.g. ApiServiceAnthropicUsage).
        if api_key is not None:
            self.api_key = api_key
            self.provider_config: Optional[ProviderConfig] = None
            client_auth_kwargs = {"api_key": api_key}
        else:
            try:
                self.provider_config = detect_provider()
                # Drop the competing-credential env var so the SDK can't
                # silently env-fallback past the auth path we just resolved.
                # Without this, anthropic.Anthropic(auth_token=...) still
                # picks up ANTHROPIC_API_KEY from os.environ and sends BOTH
                # auth headers — the gateway then honours X-Api-Key and bills
                # the Console org even though Max was chosen.
                scrub_competing_env(self.provider_config)
            except ProviderResolutionError:
                # Preserve legacy behaviour: if no detect-able creds, fall
                # back to the env var read so existing callers that relied
                # on ANTHROPIC_API_KEY-only setups still construct a client
                # (it will just fail at call time if the key is bogus).
                self.provider_config = None
                self.api_key = os.environ.get("ANTHROPIC_API_KEY")
                client_auth_kwargs = {"api_key": self.api_key}
            else:
                if self.provider_config.kind == PROVIDER_CLAUDE_CODE:
                    self.api_key = None
                    client_auth_kwargs = {"auth_token": self.provider_config.auth_token}
                else:
                    self.api_key = self.provider_config.api_key
                    client_auth_kwargs = {"api_key": self.provider_config.api_key}

        self.model = config.app_data.get('model', self.DEFAULT_MODEL)
        self.max_tokens = config.app_data.get('max_tokens', self.DEFAULT_MAX_TOKENS)
        self.max_retries = int(config.app_data.get('max_retries', self.DEFAULT_MAX_RETRIES))
        self.retry_base_delay = float(config.app_data.get('retry_base_delay', self.DEFAULT_RETRY_BASE_DELAY))
        self.retry_max_delay = float(config.app_data.get('retry_max_delay', self.DEFAULT_RETRY_MAX_DELAY))

        self.base_client: Optional[Anthropic] = None
        self.async_client: Optional[AsyncAnthropic] = None

        if self.use_base_client:
            self.base_client = Anthropic(max_retries=0, **client_auth_kwargs)
            self.async_client = AsyncAnthropic(max_retries=0, **client_auth_kwargs)
        else:
            # Subclass uses its own transport (e.g. ApiServiceAnthropicUsage
            # talks to the admin API directly via httpx with its own key).
            # Skip SDK client construction entirely.
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

    # region Provider fallback (Max → API on quota / rate-limit)

    def _looks_like_quota_error(self, exc: BaseException) -> bool:
        if isinstance(exc, RateLimitError):
            return True
        if isinstance(exc, APIStatusError):
            msg = str(exc).lower()
            return any(p in msg for p in _USAGE_LIMIT_PATTERNS)
        return False

    def _maybe_swap_to_fallback(self, exc: BaseException) -> bool:
        """If the current provider has a fallback wired and ``exc`` looks
        like a quota/rate-limit hit, rebuild ``base_client`` and
        ``async_client`` against the fallback provider and return True.

        One-directional: Max → API. The new ProviderConfig has no further
        fallback so a second quota hit on the API path properly raises.
        """
        if self.provider_config is None or self.provider_config.fallback is None:
            return False
        if not self._looks_like_quota_error(exc):
            return False

        fb = self.provider_config.fallback
        log.warning(
            "Anthropic %s on provider=%s — falling back to %s",
            type(exc).__name__, self.provider_config.kind, fb.kind,
        )
        self.provider_config = fb
        if fb.kind == PROVIDER_CLAUDE_CODE:
            kw = {"auth_token": fb.auth_token}
            self.api_key = None
        else:
            kw = {"api_key": fb.api_key}
            self.api_key = fb.api_key
        self.base_client = Anthropic(max_retries=0, **kw)
        self.async_client = AsyncAnthropic(max_retries=0, **kw)
        return True

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

        try:
            return self._with_backoff(self.base_client.messages.create, **payload)
        except APIStatusError as exc:
            if self._maybe_swap_to_fallback(exc):
                return self._with_backoff(self.base_client.messages.create, **payload)
            raise

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

        try:
            return await self._with_backoff_async(self.async_client.messages.create, **payload)
        except APIStatusError as exc:
            if self._maybe_swap_to_fallback(exc):
                return await self._with_backoff_async(self.async_client.messages.create, **payload)
            raise

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

        kwargs = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            return self._with_backoff(self.base_client.messages.count_tokens, **kwargs)
        except APIStatusError as exc:
            if self._maybe_swap_to_fallback(exc):
                return self._with_backoff(self.base_client.messages.count_tokens, **kwargs)
            raise
