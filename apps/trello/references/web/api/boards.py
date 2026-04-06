from typing import List

from apps.trello.references.dto.board import DtoTrelloBoard, DtoTrelloList, DtoTrelloCard
from apps.trello.references.web.base_api_service import BaseApiServiceTrello
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTrelloBoards(BaseApiServiceTrello):
    """
    Trello REST API — board and list operations.

    Methods:
        get_my_boards()         → All boards for the authenticated member
        get_board()             → Single board by ID
        get_board_lists()       → All lists on a board
        get_board_cards()       → All cards on a board
        create_board()          → Create a new board
        archive_board()         → Close (archive) a board
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceTrelloBoards, self).__init__(config, **kwargs)

    @deserialized(List[dict])
    def get_my_boards(self):
        """Return all boards for the authenticated member."""
        self.request.get() \
            .add_uri_parameter('members') \
            .add_uri_parameter('me') \
            .add_uri_parameter('boards')

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_board(self, board_id: str):
        """
        Get a single board by ID.

        Args:
            board_id: The board's 24-char Trello ID.
        """
        self.request.get() \
            .add_uri_parameter('boards') \
            .add_uri_parameter(board_id)

        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_board_lists(self, board_id: str, filter: str = 'open'):
        """
        Get all lists on a board.

        Args:
            board_id: The board's 24-char Trello ID.
            filter:   'all', 'open' (default), or 'closed'.
        """
        self.request.get() \
            .add_uri_parameter('boards') \
            .add_uri_parameter(board_id) \
            .add_uri_parameter('lists') \
            .add_query_string('filter', filter)

        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_board_cards(self, board_id: str, filter: str = 'open'):
        """
        Get all cards on a board.

        Args:
            board_id: The board's 24-char Trello ID.
            filter:   'all', 'open' (default), 'closed', or 'visible'.
        """
        self.request.get() \
            .add_uri_parameter('boards') \
            .add_uri_parameter(board_id) \
            .add_uri_parameter('cards') \
            .add_query_string('filter', filter)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_board(self, name: str, desc: str = None, id_organization: str = None):
        """
        Create a new board.

        Args:
            name:            Board name (required).
            desc:            Optional board description.
            id_organization: Optional workspace ID to create the board in.
        """
        payload = {'name': name}
        if desc:
            payload['desc'] = desc
        if id_organization:
            payload['idOrganization'] = id_organization

        self.request.post() \
            .add_uri_parameter('boards') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def archive_board(self, board_id: str):
        """
        Close (archive) a board.

        Args:
            board_id: The board's 24-char Trello ID.
        """
        self.request.put() \
            .add_uri_parameter('boards') \
            .add_uri_parameter(board_id) \
            .add_json_payload({'closed': True})

        return self.client.execute_request(self.request.build())
