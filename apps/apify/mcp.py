"""
MCP tools for Apify.

API reference: https://docs.apify.com/api/v2
Base URL:      https://api.apify.com/v2 — Bearer token auth.

Tool surface focuses on the harqis-work use cases:
  - Run any actor (sync), inspect actors, runs, datasets
  - Trends helpers across Google Trends + Instagram + Facebook + TikTok + Reddit
  - One-shot ``apify_aggregate_trends`` to compare a keyword across platforms
"""
import logging
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import FastMCP
from apps.apify.config import CONFIG
from apps.apify.references.web.api.actors import ApiServiceApifyActors
from apps.apify.references.web.api.runs import ApiServiceApifyRuns
from apps.apify.references.web.api.datasets import ApiServiceApifyDatasets
from apps.apify.references.web.api.trends import ApiServiceApifyTrends, DEFAULT_ACTORS

logger = logging.getLogger("harqis-mcp.apify")


def _as_dict(result) -> dict:
    return result if isinstance(result, dict) else {}


def _as_list(result) -> list:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    return []


def register_apify_tools(mcp: FastMCP):

    # ── Actors ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def apify_list_actors(my: bool = False, limit: int = 50) -> dict:
        """List actors visible to the configured Apify token.

        Args:
            my:    If True, only return actors owned by the token user.
            limit: Max actors to return.
        """
        logger.info("Tool called: apify_list_actors my=%s limit=%s", my, limit)
        result = ApiServiceApifyActors(CONFIG).list_actors(my=my, limit=limit)
        return _as_dict(result)

    @mcp.tool()
    def apify_get_actor(actor_id: str) -> dict:
        """Get full metadata for one actor.

        Args:
            actor_id: ``username/actor-name`` (canonical) or hex actor ID.
        """
        logger.info("Tool called: apify_get_actor id=%s", actor_id)
        result = ApiServiceApifyActors(CONFIG).get_actor(actor_id)
        return _as_dict(result)

    @mcp.tool()
    def apify_run_actor_sync(actor_id: str, input_payload: Optional[Dict[str, Any]] = None,
                             timeout_secs: int = 180, limit: int = 100) -> list:
        """Run an actor synchronously and return its dataset items.

        Blocks for up to 5 minutes (or ``timeout_secs``). Use this for
        scrapers that finish quickly; for longer jobs use ``apify_run_actor``
        and poll ``apify_get_run``.

        Args:
            actor_id:      ``username/actor-name`` or hex ID.
            input_payload: JSON object matching the actor's input schema.
            timeout_secs:  Hard timeout for the run.
            limit:         Max items to return.
        """
        logger.info("Tool called: apify_run_actor_sync actor=%s", actor_id)
        result = ApiServiceApifyActors(CONFIG).run_actor_sync(
            actor_id, input_payload=input_payload,
            timeout_secs=timeout_secs, limit=limit)
        items = _as_list(result)
        logger.info("apify_run_actor_sync returned %d item(s)", len(items))
        return items

    @mcp.tool()
    def apify_run_actor(actor_id: str, input_payload: Optional[Dict[str, Any]] = None,
                        timeout_secs: Optional[int] = None) -> dict:
        """Start an asynchronous actor run. Returns the run object.

        The caller is responsible for polling ``apify_get_run`` until
        ``status == 'SUCCEEDED'`` and then calling ``apify_get_dataset_items``
        with the run's ``defaultDatasetId``.

        Args:
            actor_id:      ``username/actor-name`` or hex ID.
            input_payload: JSON object matching the actor's input schema.
            timeout_secs:  Optional per-run timeout.
        """
        logger.info("Tool called: apify_run_actor actor=%s", actor_id)
        result = ApiServiceApifyActors(CONFIG).run_actor(
            actor_id, input_payload=input_payload, timeout_secs=timeout_secs)
        return _as_dict(result)

    # ── Runs ───────────────────────────────────────────────────────────────

    @mcp.tool()
    def apify_list_runs(status: Optional[str] = None, limit: int = 25) -> dict:
        """List recent actor runs across the account.

        Args:
            status: Filter — e.g. 'SUCCEEDED', 'FAILED', 'RUNNING'.
            limit:  Max runs to return.
        """
        logger.info("Tool called: apify_list_runs status=%s limit=%s", status, limit)
        result = ApiServiceApifyRuns(CONFIG).list_runs(status=status, limit=limit)
        return _as_dict(result)

    @mcp.tool()
    def apify_get_run(run_id: str) -> dict:
        """Get a single run's status, dataset/store IDs, and stats.

        Args:
            run_id: The run identifier returned by ``apify_run_actor``.
        """
        logger.info("Tool called: apify_get_run id=%s", run_id)
        result = ApiServiceApifyRuns(CONFIG).get_run(run_id)
        return _as_dict(result)

    # ── Datasets ───────────────────────────────────────────────────────────

    @mcp.tool()
    def apify_get_dataset_items(dataset_id: str, limit: int = 100,
                                offset: int = 0, fields: Optional[List[str]] = None) -> list:
        """Fetch items from a dataset (typically a finished run's defaultDatasetId).

        Args:
            dataset_id: Dataset ID.
            limit:      Max items.
            offset:     Pagination offset.
            fields:     Optional whitelist of field names to keep.
        """
        logger.info("Tool called: apify_get_dataset_items id=%s limit=%s",
                    dataset_id, limit)
        result = ApiServiceApifyDatasets(CONFIG).get_dataset_items(
            dataset_id, limit=limit, offset=offset, fields=fields)
        items = _as_list(result)
        logger.info("apify_get_dataset_items returned %d item(s)", len(items))
        return items

    # ── Trends ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def apify_google_trends(keywords: List[str], geo: str = '',
                            timeframe: str = 'today 1-m') -> list:
        """Search Google Trends for keywords with a location and time window.

        Args:
            keywords:  Up to 5 search terms compared on the same chart.
            geo:       ISO country code ('US', 'PH', 'GB') or '' for worldwide.
            timeframe: e.g. 'now 7-d', 'today 1-m', 'today 12-m', 'today 5-y', 'all'.
        """
        logger.info("Tool called: apify_google_trends keywords=%s geo=%s tf=%s",
                    keywords, geo, timeframe)
        result = ApiServiceApifyTrends(CONFIG).search_google_trends(
            keywords, geo=geo, timeframe=timeframe)
        items = _as_list(result)
        logger.info("apify_google_trends returned %d item(s)", len(items))
        return items

    @mcp.tool()
    def apify_instagram_hashtag(hashtags: List[str], results_limit: int = 50) -> list:
        """Get recent Instagram posts for one or more hashtags.

        Args:
            hashtags:      Hashtag list — without the leading '#'.
            results_limit: Max posts per hashtag.
        """
        logger.info("Tool called: apify_instagram_hashtag tags=%s limit=%s",
                    hashtags, results_limit)
        result = ApiServiceApifyTrends(CONFIG).search_instagram_hashtag(
            hashtags, results_limit=results_limit)
        return _as_list(result)

    @mcp.tool()
    def apify_facebook_posts(page_urls_or_queries: List[str],
                             results_limit: int = 50) -> list:
        """Scrape recent Facebook posts from page URLs or search queries.

        Args:
            page_urls_or_queries: Page URLs (https://facebook.com/<page>) or text queries.
            results_limit:        Max posts per input.
        """
        logger.info("Tool called: apify_facebook_posts inputs=%d limit=%s",
                    len(page_urls_or_queries), results_limit)
        result = ApiServiceApifyTrends(CONFIG).search_facebook_posts(
            page_urls_or_queries, results_limit=results_limit)
        return _as_list(result)

    @mcp.tool()
    def apify_tiktok(hashtags_or_keywords: List[str],
                     results_per_page: int = 30) -> list:
        """Scrape recent TikTok videos for hashtags or keywords.

        Args:
            hashtags_or_keywords: Hashtag (with or without '#') or keyword list.
            results_per_page:     Max videos per input.
        """
        logger.info("Tool called: apify_tiktok inputs=%s",
                    hashtags_or_keywords)
        result = ApiServiceApifyTrends(CONFIG).search_tiktok(
            hashtags_or_keywords, results_per_page=results_per_page)
        return _as_list(result)

    @mcp.tool()
    def apify_reddit(keywords: List[str], subreddits: Optional[List[str]] = None,
                     sort: str = 'new', max_items: int = 50) -> list:
        """Scrape Reddit posts matching keywords, optionally restricted to subreddits.

        Args:
            keywords:   Free-text search terms.
            subreddits: Optional restrict-to list (without 'r/').
            sort:       'new' | 'hot' | 'top' | 'relevance'. Default 'new'.
            max_items:  Total cap across all queries.
        """
        logger.info("Tool called: apify_reddit keywords=%s subreddits=%s",
                    keywords, subreddits)
        result = ApiServiceApifyTrends(CONFIG).search_reddit(
            keywords, subreddits=subreddits, sort=sort, max_items=max_items)
        return _as_list(result)

    @mcp.tool()
    def apify_aggregate_trends(query: str,
                               platforms: Optional[List[str]] = None,
                               location: str = '',
                               timeframe: str = 'today 1-m',
                               per_platform_limit: int = 25) -> list:
        """Run one query across several social platforms and return normalised items.

        Useful for market research: a single keyword (e.g. 'AI', 'space',
        '#climate') is fanned out to Google Trends, Instagram, Facebook,
        TikTok, and Reddit, then results are projected onto a common shape
        (platform / title / url / author / posted_at / engagement / score).

        Args:
            query:              Single keyword or hashtag to search on every platform.
            platforms:          Subset of {google_trends, instagram, facebook, tiktok, reddit}.
                                None means all five.
            location:           ISO country code, applied to Google Trends only.
            timeframe:          Google Trends timeframe (e.g. 'today 1-m', 'today 12-m').
            per_platform_limit: Max items requested per platform.
        """
        logger.info("Tool called: apify_aggregate_trends query=%s platforms=%s loc=%s",
                    query, platforms, location)
        result = ApiServiceApifyTrends(CONFIG).aggregate_trends(
            query, platforms=platforms, location=location,
            timeframe=timeframe, per_platform_limit=per_platform_limit)
        items = _as_list(result)
        logger.info("apify_aggregate_trends returned %d item(s)", len(items))
        return items

    @mcp.tool()
    def apify_default_actors() -> dict:
        """Show the default actor IDs used by the trends helpers.

        Override per-call by passing ``actor_id=...`` to a search method,
        or by editing ``apps/apify/references/web/api/trends.py:DEFAULT_ACTORS``.
        """
        logger.info("Tool called: apify_default_actors")
        return dict(DEFAULT_ACTORS)
