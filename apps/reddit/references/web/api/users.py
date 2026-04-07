from apps.reddit.references.web.base_api_service import BaseApiServiceReddit
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceRedditUsers(BaseApiServiceReddit):
    """
    Reddit API — user profile, karma, history, and inbox.

    Methods:
        get_me()            → Authenticated user's full profile
        get_karma()         → Karma breakdown by subreddit
        get_user()          → Any user's public profile
        get_submitted()     → User's submitted posts
        get_comments()      → User's comment history
        get_saved()         → User's saved posts/comments
        get_inbox()         → Inbox messages (all/unread/sent)
        send_message()      → Send a private message
        mark_read()         → Mark messages as read
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceRedditUsers, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_me(self):
        """Get the authenticated user's full profile including karma and inbox status."""
        self.request.get() \
            .add_uri_parameter('api') \
            .add_uri_parameter('v1') \
            .add_uri_parameter('me') \
            .add_query_string('raw_json', 1)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_karma(self):
        """Get karma breakdown by subreddit for the authenticated user."""
        self.request.get() \
            .add_uri_parameter('api') \
            .add_uri_parameter('v1') \
            .add_uri_parameter('me') \
            .add_uri_parameter('karma') \
            .add_query_string('raw_json', 1)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_user(self, username: str):
        """
        Get a user's public profile.

        Args:
            username: Reddit username (without u/ prefix).

        Returns:
            t2 object with name, karma, created_utc, icon_img, is_mod.
        """
        self.request.get() \
            .add_uri_parameter('user') \
            .add_uri_parameter(username) \
            .add_uri_parameter('about') \
            .add_query_string('raw_json', 1)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_submitted(self, username: str, limit: int = 25,
                      sort: str = 'new', after: str = None):
        """
        Get a user's submitted posts.

        Args:
            username: Reddit username.
            limit:    Max posts (1–100). Default 25.
            sort:     'hot','new','top','controversial'. Default 'new'.
            after:    Pagination cursor.
        """
        self.request.get() \
            .add_uri_parameter('user') \
            .add_uri_parameter(username) \
            .add_uri_parameter('submitted') \
            .add_query_string('limit', limit) \
            .add_query_string('sort', sort) \
            .add_query_string('raw_json', 1)
        if after:
            self.request.add_query_string('after', after)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_comments_history(self, username: str, limit: int = 25, after: str = None):
        """
        Get a user's comment history.

        Args:
            username: Reddit username.
            limit:    Max comments (1–100). Default 25.
            after:    Pagination cursor.
        """
        self.request.get() \
            .add_uri_parameter('user') \
            .add_uri_parameter(username) \
            .add_uri_parameter('comments') \
            .add_query_string('limit', limit) \
            .add_query_string('raw_json', 1)
        if after:
            self.request.add_query_string('after', after)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_saved(self, username: str, limit: int = 25, after: str = None):
        """
        Get the authenticated user's saved posts and comments.

        Requires 'history' scope.

        Args:
            username: Your own Reddit username.
            limit:    Max items (1–100). Default 25.
            after:    Pagination cursor.
        """
        self.request.get() \
            .add_uri_parameter('user') \
            .add_uri_parameter(username) \
            .add_uri_parameter('saved') \
            .add_query_string('limit', limit) \
            .add_query_string('raw_json', 1)
        if after:
            self.request.add_query_string('after', after)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_inbox(self, filter: str = 'inbox', limit: int = 25, after: str = None):
        """
        Get inbox messages.

        Args:
            filter: 'inbox' (all), 'unread', 'sent', 'mentions', 'comments', 'selfreply'.
            limit:  Max messages (1–100). Default 25.
            after:  Pagination cursor.
        """
        self.request.get() \
            .add_uri_parameter('message') \
            .add_uri_parameter(filter) \
            .add_query_string('limit', limit) \
            .add_query_string('raw_json', 1)
        if after:
            self.request.add_query_string('after', after)
        return self.client.execute_request(self.request.build())

    def send_message(self, to: str, subject: str, text: str) -> dict:
        """
        Send a private message to another user.

        Requires 'privatemessages' scope.

        Args:
            to:      Recipient username (without u/ prefix).
            subject: Subject line (max 100 chars).
            text:    Message body (markdown).
        """
        return self._post_form('/api/compose', {
            'to': to,
            'subject': subject,
            'text': text,
            'api_type': 'json',
        })

    def mark_read(self, *fullnames: str) -> dict:
        """
        Mark messages as read.

        Args:
            *fullnames: One or more message fullnames (e.g. 't4_abc123').
        """
        return self._post_form('/api/read_message', {
            'id': ','.join(fullnames),
        })
