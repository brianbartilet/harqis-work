import os
from datetime import datetime, timezone
from typing import Optional, List

import httpx

from apps.antropic.references.dto.usage import DtoAnthropicUsageEntry, DtoAnthropicUsageSummary
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

# Pricing per million tokens (USD) as of April 2026.
# Source: https://www.anthropic.com/pricing
# Update these if Anthropic changes pricing.
_PRICING: dict = {
    # Model name fragments → (input $/M, output $/M, cache_write $/M, cache_read $/M)
    "claude-opus-4":        (15.00, 75.00,  18.75,  1.50),
    "claude-sonnet-4":       (3.00, 15.00,   3.75,  0.30),
    "claude-haiku-4":        (0.80,  4.00,   1.00,  0.08),
    "claude-opus-3":        (15.00, 75.00,  18.75,  1.50),
    "claude-sonnet-3-7":     (3.00, 15.00,   3.75,  0.30),
    "claude-sonnet-3-5":     (3.00, 15.00,   3.75,  0.30),
    "claude-haiku-3-5":      (0.80,  4.00,   1.00,  0.08),
    "claude-haiku-3":        (0.25,  1.25,   0.30,  0.03),
}
_DEFAULT_PRICING = (3.00, 15.00, 3.75, 0.30)  # fallback: Sonnet 4 pricing


def _get_pricing(model: str) -> tuple:
    """Return (input, output, cache_write, cache_read) $/M for the model."""
    model_lower = (model or "").lower()
    for key, prices in _PRICING.items():
        if key in model_lower:
            return prices
    return _DEFAULT_PRICING


def _estimate_cost(entry: DtoAnthropicUsageEntry) -> float:
    """Calculate estimated USD cost for a single usage entry."""
    inp, out, cw, cr = _get_pricing(entry.model or "")
    m = 1_000_000
    cost = (
        (entry.input_tokens or 0) / m * inp
        + (entry.output_tokens or 0) / m * out
        + (entry.cache_creation_input_tokens or 0) / m * cw
        + (entry.cache_read_input_tokens or 0) / m * cr
    )
    return round(cost, 6)


class ApiServiceAnthropicUsage(BaseApiServiceAnthropic):
    """
    Anthropic Admin API — usage and cost reporting.

    Uses the Anthropic usage API endpoint directly via httpx (not the SDK).
    Requires an Admin API key — the regular API key does not have access.

    Get your Admin API key at: https://console.anthropic.com/settings/keys

    Environment variable: ANTHROPIC_ADMIN_KEY
    Falls back to ANTHROPIC_API_KEY if ANTHROPIC_ADMIN_KEY is not set.

    Docs: https://docs.anthropic.com/en/api/usage
    """

    _BASE = "https://api.anthropic.com/v1"
    _ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, config, **kwargs):
        super().__init__(config, use_base_client=False, **kwargs)
        admin_key = (
            kwargs.get("admin_key")
            or os.environ.get("ANTHROPIC_ADMIN_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )
        self._headers = {
            "x-api-key": admin_key,
            "anthropic-version": self._ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        """Make a GET request, converting non-2xx responses to clear errors."""
        resp = httpx.get(
            f"{self._BASE}/{path}",
            headers=self._headers,
            params={k: v for k, v in (params or {}).items() if v is not None},
            timeout=30,
        )
        data = resp.json()
        if not resp.is_success:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            raise PermissionError(
                f"Anthropic usage API {resp.status_code} [{err.get('type', 'error')}]: "
                f"{err.get('message', resp.text)}. "
                "The usage API requires an Admin API key. "
                "Set ANTHROPIC_ADMIN_KEY from "
                "https://console.anthropic.com/settings/keys"
            )
        return data

    def get_usage(self, start_time: str, end_time: str = None,
                  workspace_id: str = None, api_key_id: str = None,
                  model: str = None, granularity: str = "day") -> DtoAnthropicUsageSummary:
        """
        Retrieve token usage data from the Anthropic usage API.

        Args:
            start_time:   ISO 8601 date string, e.g. '2026-04-01' or '2026-04-01T00:00:00Z'.
            end_time:     ISO 8601 date string (default: now).
            workspace_id: Filter by workspace ID (optional).
            api_key_id:   Filter by API key ID (optional).
            model:        Filter by model name (optional).
            granularity:  'day' or 'month' (default: 'day').

        Returns:
            DtoAnthropicUsageSummary with per-model breakdown and cost estimates.
        """
        params = {
            "start_time": start_time,
            "end_time": end_time,
            "workspace_id": workspace_id,
            "api_key_id": api_key_id,
            "model": model,
            "granularity": granularity,
        }
        data = self._get("usage", params)
        return self._parse_summary(data, start_time, end_time)

    def get_month_to_date(self, workspace_id: str = None,
                          api_key_id: str = None) -> DtoAnthropicUsageSummary:
        """
        Retrieve month-to-date usage and estimated cost.

        Automatically sets start_time to the first of the current month (UTC)
        and end_time to now.

        Args:
            workspace_id: Filter by workspace ID (optional).
            api_key_id:   Filter by API key ID (optional).

        Returns:
            DtoAnthropicUsageSummary for the current calendar month.
        """
        now = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.get_usage(
            start_time=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_time=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            workspace_id=workspace_id,
            api_key_id=api_key_id,
            granularity="day",
        )

    def _parse_summary(self, data: dict, start_time: str,
                       end_time: str) -> DtoAnthropicUsageSummary:
        """Parse raw API response into DtoAnthropicUsageSummary with cost estimates."""
        # The usage API returns an aggregated list; aggregate across dates by model
        aggregated: dict[str, DtoAnthropicUsageEntry] = {}

        raw_items = data.get("data", data.get("usage", []))
        for item in raw_items:
            model_name = item.get("model", "unknown")
            if model_name not in aggregated:
                aggregated[model_name] = DtoAnthropicUsageEntry(model=model_name)
            entry = aggregated[model_name]
            entry.input_tokens = (entry.input_tokens or 0) + (item.get("input_tokens") or 0)
            entry.output_tokens = (entry.output_tokens or 0) + (item.get("output_tokens") or 0)
            entry.cache_creation_input_tokens = (
                (entry.cache_creation_input_tokens or 0)
                + (item.get("cache_creation_input_tokens") or 0)
            )
            entry.cache_read_input_tokens = (
                (entry.cache_read_input_tokens or 0)
                + (item.get("cache_read_input_tokens") or 0)
            )

        by_model: List[DtoAnthropicUsageEntry] = []
        total_in = total_out = total_cw = total_cr = 0
        total_cost = 0.0

        for entry in aggregated.values():
            entry.estimated_cost_usd = _estimate_cost(entry)
            total_in += entry.input_tokens or 0
            total_out += entry.output_tokens or 0
            total_cw += entry.cache_creation_input_tokens or 0
            total_cr += entry.cache_read_input_tokens or 0
            total_cost += entry.estimated_cost_usd
            by_model.append(entry)

        by_model.sort(key=lambda e: e.estimated_cost_usd or 0, reverse=True)

        return DtoAnthropicUsageSummary(
            start_time=start_time,
            end_time=end_time,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_cache_creation_tokens=total_cw,
            total_cache_read_tokens=total_cr,
            estimated_total_cost_usd=round(total_cost, 6),
            by_model=by_model,
        )
