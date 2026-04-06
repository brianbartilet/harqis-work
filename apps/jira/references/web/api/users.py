from typing import List

from apps.jira.references.web.base_api_service import BaseApiServiceJira
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceJiraUsers(BaseApiServiceJira):
    """
    Jira Cloud REST API v3 — user operations.

    Methods:
        get_myself()        → Authenticated user's profile
        search_users()      → Search for users by query string
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceJiraUsers, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_myself(self):
        """Return the authenticated user's Jira profile."""
        self.request.get() \
            .add_uri_parameter('myself')

        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def search_users(self, query: str, max_results: int = 50, start_at: int = 0):
        """
        Search for users by display name, email, or username.

        Args:
            query:       Search string.
            max_results: Maximum results to return (default 50).
            start_at:    Pagination offset (default 0).
        """
        self.request.get() \
            .add_uri_parameter('user') \
            .add_uri_parameter('search') \
            .add_query_string('username', query) \
            .add_query_string('maxResults', max_results) \
            .add_query_string('startAt', start_at)

        return self.client.execute_request(self.request.build())
