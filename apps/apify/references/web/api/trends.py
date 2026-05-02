"""
High-level trends and social-media aggregation helpers.

These methods wrap well-known *public* Apify actors so callers do not have to
remember each actor's input schema. Every method is a thin convenience over
``ApiServiceApifyActors.run_actor_sync`` — the actor IDs are kept in
``DEFAULT_ACTORS`` and can be overridden per call (so a paying user can
swap to a private/premium actor without changing call sites).

Reference: https://apify.com/store
"""
from typing import Optional, List, Dict, Any

from apps.apify.references.web.api.actors import ApiServiceApifyActors
from apps.apify.references.web.base_api_service import BaseApiServiceApify
from apps.apify.references.dto.trend import DtoApifyTrendItem


# Default actor IDs per platform. Override per call via the ``actor_id`` kwarg.
DEFAULT_ACTORS: Dict[str, str] = {
    'google_trends': 'apify/google-trends-scraper',
    'instagram':     'apify/instagram-hashtag-scraper',
    'facebook':      'apify/facebook-posts-scraper',
    'tiktok':        'clockworks/free-tiktok-scraper',
    'reddit':        'trudax/reddit-scraper-lite',
}


class ApiServiceApifyTrends(BaseApiServiceApify):
    """
    Cross-platform trends aggregation.

    Methods:
        search_google_trends()       → Trending keywords with location/time/related cuts
        search_instagram_hashtag()   → Recent IG posts for a hashtag
        search_facebook_posts()      → Recent FB posts from pages/keywords
        search_tiktok()              → Recent TikTok videos by hashtag/keyword
        search_reddit()              → Reddit posts matching a query
        aggregate_trends()           → Run several platforms in one call, return normalised items
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceApifyTrends, self).__init__(config, **kwargs)
        self._actors = ApiServiceApifyActors(config, **kwargs)

    # ── Per-platform helpers ───────────────────────────────────────────────

    def search_google_trends(self, keywords: List[str], geo: str = '',
                             timeframe: str = 'today 1-m',
                             category: int = 0,
                             actor_id: Optional[str] = None,
                             timeout_secs: int = 180) -> Any:
        """
        Search Google Trends for one or more keywords.

        Args:
            keywords:  Up to 5 search terms, compared on the same chart.
            geo:       ISO country code ('US', 'PH', 'GB') or '' for worldwide.
            timeframe: 'now 1-H' | 'now 4-H' | 'now 1-d' | 'now 7-d' |
                       'today 1-m' | 'today 3-m' | 'today 12-m' |
                       'today 5-y' | 'all'.
            category:  Google Trends category ID (0 = all categories).
            actor_id:  Override the default actor.
            timeout_secs: Sync run timeout.
        """
        payload = {
            'searchTerms': keywords,
            'geo': geo,
            'timeRange': timeframe,
            'category': category,
        }
        return self._actors.run_actor_sync(
            actor_id or DEFAULT_ACTORS['google_trends'],
            input_payload=payload,
            timeout_secs=timeout_secs,
        )

    def search_instagram_hashtag(self, hashtags: List[str], results_limit: int = 50,
                                 actor_id: Optional[str] = None,
                                 timeout_secs: int = 180) -> Any:
        """
        Get recent Instagram posts for one or more hashtags.

        Args:
            hashtags:      Hashtag list — without the leading ``#``.
            results_limit: Max posts per hashtag.
        """
        payload = {
            'hashtags': hashtags,
            'resultsLimit': results_limit,
        }
        return self._actors.run_actor_sync(
            actor_id or DEFAULT_ACTORS['instagram'],
            input_payload=payload,
            timeout_secs=timeout_secs,
        )

    def search_facebook_posts(self, page_urls_or_queries: List[str],
                              results_limit: int = 50,
                              actor_id: Optional[str] = None,
                              timeout_secs: int = 240) -> Any:
        """
        Scrape recent Facebook posts from page URLs or search queries.

        Args:
            page_urls_or_queries: Either ``https://facebook.com/<page>`` URLs
                                  or free-text search strings (depends on the
                                  actor's input schema — both are accepted by
                                  the default ``apify/facebook-posts-scraper``).
            results_limit:        Max posts per input.
        """
        payload = {
            'startUrls': [{'url': u} for u in page_urls_or_queries if '://' in u],
            'searchQueries': [q for q in page_urls_or_queries if '://' not in q],
            'resultsLimit': results_limit,
        }
        return self._actors.run_actor_sync(
            actor_id or DEFAULT_ACTORS['facebook'],
            input_payload=payload,
            timeout_secs=timeout_secs,
        )

    def search_tiktok(self, hashtags_or_keywords: List[str], results_per_page: int = 30,
                      actor_id: Optional[str] = None,
                      timeout_secs: int = 240) -> Any:
        """
        Scrape recent TikTok videos for hashtags or search keywords.

        Args:
            hashtags_or_keywords: Hashtag (with or without ``#``) or keyword list.
            results_per_page:     Max videos per input.
        """
        payload = {
            'hashtags': [t.lstrip('#') for t in hashtags_or_keywords],
            'resultsPerPage': results_per_page,
        }
        return self._actors.run_actor_sync(
            actor_id or DEFAULT_ACTORS['tiktok'],
            input_payload=payload,
            timeout_secs=timeout_secs,
        )

    def search_reddit(self, keywords: List[str], subreddits: Optional[List[str]] = None,
                      sort: str = 'new', max_items: int = 50,
                      actor_id: Optional[str] = None,
                      timeout_secs: int = 180) -> Any:
        """
        Scrape Reddit posts matching keywords, optionally restricted to subreddits.

        Args:
            keywords:   Free-text search terms.
            subreddits: Optional restrict-to list (without ``r/``).
            sort:       'new' | 'hot' | 'top' | 'relevance'.
            max_items:  Total cap across all queries.
        """
        searches = list(keywords)
        if subreddits:
            searches += [f'subreddit:{s}' for s in subreddits]
        payload = {
            'searches': searches,
            'sort': sort,
            'maxItems': max_items,
        }
        return self._actors.run_actor_sync(
            actor_id or DEFAULT_ACTORS['reddit'],
            input_payload=payload,
            timeout_secs=timeout_secs,
        )

    # ── Cross-platform aggregation ─────────────────────────────────────────

    def aggregate_trends(self, query: str,
                         platforms: Optional[List[str]] = None,
                         location: str = '',
                         timeframe: str = 'today 1-m',
                         per_platform_limit: int = 25) -> List[Dict[str, Any]]:
        """
        Run one query across several platforms and return normalised items.

        Args:
            query:              Single keyword or hashtag.
            platforms:          Subset of ``DEFAULT_ACTORS`` keys. ``None`` = all.
            location:           ISO country code, applied to Google Trends only.
            timeframe:          Google Trends timeframe (see ``search_google_trends``).
            per_platform_limit: Max items per platform.

        Returns:
            List of dicts compatible with :class:`DtoApifyTrendItem`.
        """
        platforms = platforms or list(DEFAULT_ACTORS.keys())
        merged: List[Dict[str, Any]] = []

        for platform in platforms:
            try:
                if platform == 'google_trends':
                    items = self.search_google_trends([query], geo=location,
                                                      timeframe=timeframe) or []
                elif platform == 'instagram':
                    items = self.search_instagram_hashtag([query.lstrip('#')],
                                                          results_limit=per_platform_limit) or []
                elif platform == 'facebook':
                    items = self.search_facebook_posts([query],
                                                       results_limit=per_platform_limit) or []
                elif platform == 'tiktok':
                    items = self.search_tiktok([query],
                                               results_per_page=per_platform_limit) or []
                elif platform == 'reddit':
                    items = self.search_reddit([query],
                                               max_items=per_platform_limit) or []
                else:
                    continue
            except Exception as e:
                merged.append({
                    'platform': platform,
                    'keyword': query,
                    'raw': {'error': str(e)},
                })
                continue

            if isinstance(items, dict):
                items = [items]

            for raw in items if isinstance(items, list) else []:
                merged.append(_normalise(platform, query, raw))

        return merged


def _normalise(platform: str, keyword: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Project a platform-specific record onto :class:`DtoApifyTrendItem`."""
    item = DtoApifyTrendItem(platform=platform, keyword=keyword, raw=raw)

    if not isinstance(raw, dict):
        return item.__dict__

    # Best-effort field mapping; missing fields stay None.
    item.title = (raw.get('title') or raw.get('text')
                  or raw.get('caption') or raw.get('description'))
    item.url = raw.get('url') or raw.get('postUrl') or raw.get('link')
    item.author = (raw.get('author') or raw.get('username')
                   or raw.get('ownerUsername') or raw.get('user'))
    item.posted_at = (raw.get('timestamp') or raw.get('createdAt')
                      or raw.get('publishedAt') or raw.get('date'))
    item.location = raw.get('location') or raw.get('geo')

    likes = raw.get('likes') or raw.get('likesCount') or raw.get('diggCount')
    views = raw.get('views') or raw.get('viewsCount') or raw.get('playCount')
    upvotes = raw.get('upvotes') or raw.get('score')
    item.score = float(likes or views or upvotes or 0) or None
    item.engagement = {
        'likes': likes, 'views': views, 'upvotes': upvotes,
        'comments': raw.get('comments') or raw.get('commentCount'),
        'shares': raw.get('shares') or raw.get('shareCount'),
    }
    if 'relatedQueries' in raw:
        item.related_terms = raw['relatedQueries']

    return item.__dict__
