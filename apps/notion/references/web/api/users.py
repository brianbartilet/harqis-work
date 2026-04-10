from typing import List, Optional

from apps.notion.references.web.base_api_service import BaseApiServiceNotion
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceNotionUsers(BaseApiServiceNotion):
    """
    Notion REST API — user operations.

    Methods:
        get_me()        → Retrieve the integration bot's user object
        get_user()      → Retrieve a user by ID
        list_users()    → List all users in the workspace
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceNotionUsers, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_me(self):
        """
        Retrieve the bot user associated with the current integration token.
        """
        self.request.get() \
            .add_uri_parameter('users') \
            .add_uri_parameter('me')

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_user(self, user_id: str):
        """
        Retrieve a user by their ID.

        Args:
            user_id: The user's UUID.
        """
        self.request.get() \
            .add_uri_parameter('users') \
            .add_uri_parameter(user_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_users(self, start_cursor: str = None, page_size: int = 100):
        """
        List all users in the workspace.

        Args:
            start_cursor: Pagination cursor from previous response.
            page_size:    Number of results per page (max 100, default 100).
        """
        self.request.get() \
            .add_uri_parameter('users') \
            .add_query_string('page_size', str(page_size))

        if start_cursor:
            self.request.add_query_string('start_cursor', start_cursor)

        return self.client.execute_request(self.request.build())
