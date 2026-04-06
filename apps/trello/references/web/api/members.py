from typing import List

from apps.trello.references.web.base_api_service import BaseApiServiceTrello
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTrelloMembers(BaseApiServiceTrello):
    """
    Trello REST API — member operations.

    Methods:
        get_me()                → Authenticated member profile
        get_member()            → Any member by ID or username
        get_member_boards()     → All boards for a member
        get_board_members()     → All members on a board
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceTrelloMembers, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_me(self):
        """Return the authenticated member's profile."""
        self.request.get() \
            .add_uri_parameter('members') \
            .add_uri_parameter('me')

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_member(self, member_id: str):
        """
        Get a member by their ID or username.

        Args:
            member_id: 24-char Trello member ID or username (e.g. 'johndoe').
        """
        self.request.get() \
            .add_uri_parameter('members') \
            .add_uri_parameter(member_id)

        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_member_boards(self, member_id: str = 'me', filter: str = 'open'):
        """
        Get all boards for a member.

        Args:
            member_id: Member ID or username. Defaults to 'me' (authenticated member).
            filter:    'all', 'open' (default), 'closed', 'starred', or 'pinned'.
        """
        self.request.get() \
            .add_uri_parameter('members') \
            .add_uri_parameter(member_id) \
            .add_uri_parameter('boards') \
            .add_query_string('filter', filter)

        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_board_members(self, board_id: str):
        """
        Get all members on a board.

        Args:
            board_id: The board's 24-char Trello ID.
        """
        self.request.get() \
            .add_uri_parameter('boards') \
            .add_uri_parameter(board_id) \
            .add_uri_parameter('members')

        return self.client.execute_request(self.request.build())
