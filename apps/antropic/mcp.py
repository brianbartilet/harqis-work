import logging
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP
from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.api.usage import ApiServiceAnthropicUsage

logger = logging.getLogger("harqis-mcp.anthropic")


def register_anthropic_tools(mcp: FastMCP):

    @mcp.tool()
    def get_anthropic_usage(start_time: str, end_time: str = None,
                            api_key_id: str = None, model: str = None,
                            granularity: str = "day") -> dict:
        """
        Get Anthropic API token usage and estimated cost for a date range.

        Requires an Admin API key set in ANTHROPIC_ADMIN_KEY (falls back to
        ANTHROPIC_API_KEY). Get an admin key at:
        https://console.anthropic.com/settings/keys

        Args:
            start_time:  Start date in ISO 8601 format, e.g. '2026-04-01'.
            end_time:    End date in ISO 8601 format (default: now).
            api_key_id:  Filter to a specific API key ID (optional).
            model:       Filter to a specific model name (optional).
            granularity: Aggregation level — 'day' or 'month' (default: 'day').

        Returns:
            Usage summary with total tokens, per-model breakdown, and estimated USD cost.
        """
        logger.info("Tool called: get_anthropic_usage start=%s end=%s", start_time, end_time)
        result = ApiServiceAnthropicUsage(get_anthropic_config()).get_usage(
            start_time=start_time,
            end_time=end_time,
            api_key_id=api_key_id,
            model=model,
            granularity=granularity,
        )
        summary = asdict(result)
        logger.info(
            "get_anthropic_usage total_cost=$%.4f input=%d output=%d",
            result.estimated_total_cost_usd,
            result.total_input_tokens,
            result.total_output_tokens,
        )
        return summary

    @mcp.tool()
    def get_anthropic_mtd_cost(api_key_id: str = None) -> dict:
        """
        Get month-to-date Anthropic API usage and estimated cost.

        Automatically covers from the 1st of the current calendar month (UTC)
        through now. Breaks down cost by model.

        Requires an Admin API key set in ANTHROPIC_ADMIN_KEY (falls back to
        ANTHROPIC_API_KEY). Get an admin key at:
        https://console.anthropic.com/settings/keys

        Args:
            api_key_id: Filter to a specific API key ID (optional).
                        Omit to see usage across all keys in the workspace.

        Returns:
            Month-to-date summary: total tokens, cost per model, total estimated USD cost.
        """
        logger.info("Tool called: get_anthropic_mtd_cost api_key_id=%s", api_key_id)
        result = ApiServiceAnthropicUsage(get_anthropic_config()).get_month_to_date(api_key_id=api_key_id)
        summary = asdict(result)
        logger.info(
            "get_anthropic_mtd_cost period=%s→%s total_cost=$%.4f",
            result.start_time,
            result.end_time,
            result.estimated_total_cost_usd,
        )
        return summary
