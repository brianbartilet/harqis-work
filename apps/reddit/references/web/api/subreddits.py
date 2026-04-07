from typing import List, Optional

from apps.reddit.references.web.base_api_service import BaseApiServiceReddit
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceRedditSubreddits(BaseApiServiceReddit):
    """
    Reddit API — subreddit listings, info, and search.

    Methods:
        get_posts()         → Fetch posts from a subreddit (hot/new/top/rising)
        get_info()          → Subreddit metadata and stats
        get_comments()      → Comments on a post
        search()            → Search posts globally or within a subreddit
        get_subscribed()    → Subreddits the authenticated user is subscribed to
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceRedditSubreddits, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_posts(self, subreddit: str, sort: str = 'hot', limit: int = 25,
                  after: str = None, t: str = None):
        """
        Fetch posts from a subreddit.

        Args:
            subreddit: Subreddit name (without r/ prefix), e.g. 'python'.
            sort:      'hot', 'new', 'top', 'rising', 'controversial'. Default 'hot'.
            limit:     Max posts to return (1–100). Default 25.
            after:     Pagination cursor — fullname of last item (e.g. 't3_abc123').
            t:         Time filter for 'top'/'controversial': 'hour','day','week','month','year','all'.

        Returns:
            Listing dict with 'data.children' list of post objects.
        """
        self.request.get() \
            .add_uri_parameter('r') \
            .add_uri_parameter(subreddit) \
            .add_uri_parameter(sort) \
            .add_query_string('limit', limit) \
            .add_query_string('raw_json', 1)
        if after:
            self.request.add_query_string('after', after)
        if t:
            self.request.add_query_string('t', t)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_info(self, subreddit: str):
        """
        Get subreddit metadata and stats.

        Args:
            subreddit: Subreddit name (without r/ prefix).

        Returns:
            t5 object with subscribers, description, active_user_count, etc.
        """
        self.request.get() \
            .add_uri_parameter('r') \
            .add_uri_parameter(subreddit) \
            .add_uri_parameter('about') \
            .add_query_string('raw_json', 1)
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_comments(self, subreddit: str, article_id: str,
                     sort: str = 'confidence', limit: int = 100):
        """
        Fetch comments for a post.

        Args:
            subreddit:  Subreddit name.
            article_id: Post ID (base-36, without 't3_' prefix).
            sort:       'confidence','top','new','controversial','old','qa'. Default 'confidence'.
            limit:      Max comments to return. Default 100.

        Returns:
            List of two Listing objects — [0] is the post, [1] is the comment tree.
        """
        self.request.get() \
            .add_uri_parameter('r') \
            .add_uri_parameter(subreddit) \
            .add_uri_parameter('comments') \
            .add_uri_parameter(article_id) \
            .add_query_string('sort', sort) \
            .add_query_string('limit', limit) \
            .add_query_string('raw_json', 1)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def search(self, query: str, subreddit: str = None, sort: str = 'relevance',
               t: str = 'all', limit: int = 25, after: str = None):
        """
        Search posts globally or within a subreddit.

        Args:
            query:     Search query string.
            subreddit: Restrict search to this subreddit. None = global search.
            sort:      'relevance','hot','top','new','comments'. Default 'relevance'.
            t:         Time filter: 'hour','day','week','month','year','all'. Default 'all'.
            limit:     Max results (1–100). Default 25.
            after:     Pagination cursor.

        Returns:
            Listing dict with matching posts.
        """
        if subreddit:
            self.request.get() \
                .add_uri_parameter('r') \
                .add_uri_parameter(subreddit) \
                .add_uri_parameter('search') \
                .add_query_string('restrict_sr', 'true')
        else:
            self.request.get().add_uri_parameter('search')

        self.request \
            .add_query_string('q', query) \
            .add_query_string('sort', sort) \
            .add_query_string('t', t) \
            .add_query_string('limit', limit) \
            .add_query_string('raw_json', 1)

        if after:
            self.request.add_query_string('after', after)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_subscribed(self, limit: int = 100, after: str = None):
        """
        List subreddits the authenticated user is subscribed to.

        Args:
            limit: Max subreddits to return (1–100). Default 100.
            after: Pagination cursor.
        """
        self.request.get() \
            .add_uri_parameter('subreddits') \
            .add_uri_parameter('mine') \
            .add_uri_parameter('subscriber') \
            .add_query_string('limit', limit) \
            .add_query_string('raw_json', 1)
        if after:
            self.request.add_query_string('after', after)
        return self.client.execute_request(self.request.build())
