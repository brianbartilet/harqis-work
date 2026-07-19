from __future__ import annotations

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from apps.looki.config import CONFIG
from apps.looki.references.adapter import build_adapter, extract_items, normalize_moment
from apps.looki.references.dto.moment import valid_moment_id

logger = logging.getLogger("harqis-mcp.looki")


def register_looki_tools(mcp: FastMCP):
    @mcp.tool()
    def looki_status() -> dict:
        """Report whether approved Looki Open API access is configured locally."""
        return build_adapter(CONFIG).status

    @mcp.tool()
    def list_looki_moments(
        since: str, until: Optional[str] = None, max_moments: int = 100
    ) -> list[dict]:
        """List privacy-bounded Looki moment metadata for an inclusive date window.

        Looki-generated descriptions are returned with
        ``generated_text_verified=false``. No media URLs or coordinates are
        included.
        """
        adapter = build_adapter(CONFIG)
        moments = adapter.list_moments(
            since=since, until=until or since, max_moments=max_moments
        )
        return [moment.to_safe_dict() for moment in moments]

    @mcp.tool()
    def search_looki_moments(
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        """Search Looki-generated labels as a coarse index, not ground truth."""
        adapter = build_adapter(CONFIG)
        moments = adapter.search_moments(
            query,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=max(1, min(page_size, 100)),
        )
        return [moment.to_safe_dict() for moment in moments]

    @mcp.tool()
    def get_looki_moment(moment_id: str) -> dict:
        """Get one Looki moment, normalized to safe metadata only."""
        exact_id = valid_moment_id(moment_id)
        if exact_id is None:
            raise ValueError("Invalid Looki moment_id")
        payload = build_adapter(CONFIG).get_moment(exact_id)
        items = extract_items(payload)
        if items:
            return normalize_moment(items[0]).to_safe_dict()
        if isinstance(payload, dict):
            candidate = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if isinstance(candidate, dict):
                return normalize_moment(candidate).to_safe_dict()
        return {}

    @mcp.tool()
    def list_looki_moment_files(
        moment_id: str,
        highlight: Optional[bool] = None,
        cursor_id: Optional[str] = None,
        limit: int = 20,
        include_temporary_urls: bool = False,
    ) -> dict:
        """List source-media metadata for explicit verification.

        Expiring signed URLs are removed by default. Set
        ``include_temporary_urls=true`` only for immediate, explicit media
        retrieval; URLs are short-lived and must not be persisted.
        """
        exact_id = valid_moment_id(moment_id)
        if exact_id is None:
            raise ValueError("Invalid Looki moment_id")
        result = build_adapter(CONFIG).list_moment_files(
            exact_id,
            highlight=highlight,
            cursor_id=cursor_id,
            limit=max(1, min(limit, 100)),
            include_temporary_urls=include_temporary_urls,
        )
        return result if isinstance(result, dict) else {"items": result}
