import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from apps.trello.config import CONFIG
from apps.trello.references.web.api.boards import ApiServiceTrelloBoards
from apps.trello.references.web.api.cards import ApiServiceTrelloCards
from apps.trello.references.web.api.members import ApiServiceTrelloMembers

logger = logging.getLogger("harqis-mcp.trello")


def register_trello_tools(mcp: FastMCP):

    @mcp.tool()
    def get_trello_my_boards() -> list[dict]:
        """Get all Trello boards for the authenticated member."""
        logger.info("Tool called: get_trello_my_boards")
        result = ApiServiceTrelloBoards(CONFIG).get_my_boards()
        result = result if isinstance(result, list) else []
        logger.info("get_trello_my_boards returned %d board(s)", len(result))
        return result

    @mcp.tool()
    def get_trello_board(board_id: str) -> dict:
        """
        Get details of a single Trello board.

        Args:
            board_id: The board's 24-char Trello ID.
        """
        logger.info("Tool called: get_trello_board board_id=%s", board_id)
        result = ApiServiceTrelloBoards(CONFIG).get_board(board_id)
        result = result if isinstance(result, dict) else {}
        logger.info("get_trello_board name=%s", result.get("name"))
        return result

    @mcp.tool()
    def get_trello_board_lists(board_id: str, filter: str = 'open') -> list[dict]:
        """
        Get all lists on a Trello board.

        Args:
            board_id: The board's 24-char Trello ID.
            filter:   'all', 'open' (default), or 'closed'.
        """
        logger.info("Tool called: get_trello_board_lists board_id=%s filter=%s", board_id, filter)
        result = ApiServiceTrelloBoards(CONFIG).get_board_lists(board_id, filter=filter)
        result = result if isinstance(result, list) else []
        logger.info("get_trello_board_lists returned %d list(s)", len(result))
        return result

    @mcp.tool()
    def get_trello_board_cards(board_id: str, filter: str = 'open') -> list[dict]:
        """
        Get all cards on a Trello board.

        Args:
            board_id: The board's 24-char Trello ID.
            filter:   'all', 'open' (default), 'closed', or 'visible'.
        """
        logger.info("Tool called: get_trello_board_cards board_id=%s filter=%s", board_id, filter)
        result = ApiServiceTrelloBoards(CONFIG).get_board_cards(board_id, filter=filter)
        result = result if isinstance(result, list) else []
        logger.info("get_trello_board_cards returned %d card(s)", len(result))
        return result

    @mcp.tool()
    def get_trello_list_cards(list_id: str) -> list[dict]:
        """
        Get all cards in a specific Trello list.

        Args:
            list_id: The list's 24-char Trello ID.
        """
        logger.info("Tool called: get_trello_list_cards list_id=%s", list_id)
        result = ApiServiceTrelloCards(CONFIG).get_list_cards(list_id)
        result = result if isinstance(result, list) else []
        logger.info("get_trello_list_cards returned %d card(s)", len(result))
        return result

    @mcp.tool()
    def get_trello_card(card_id: str) -> dict:
        """
        Get details of a single Trello card.

        Args:
            card_id: The card's 24-char Trello ID.
        """
        logger.info("Tool called: get_trello_card card_id=%s", card_id)
        result = ApiServiceTrelloCards(CONFIG).get_card(card_id)
        result = result if isinstance(result, dict) else {}
        logger.info("get_trello_card name=%s", result.get("name"))
        return result

    @mcp.tool()
    def create_trello_card(list_id: str, name: str, desc: str = None, due: str = None) -> dict:
        """
        Create a new card in a Trello list.

        Args:
            list_id: Target list ID (required).
            name:    Card name (required).
            desc:    Optional card description.
            due:     Optional due date in ISO 8601 format (e.g. '2026-04-10T09:00:00.000Z').
        """
        logger.info("Tool called: create_trello_card list_id=%s name=%s", list_id, name)
        result = ApiServiceTrelloCards(CONFIG).create_card(list_id=list_id, name=name, desc=desc, due=due)
        result = result if isinstance(result, dict) else {}
        logger.info("create_trello_card created id=%s", result.get("id"))
        return result

    @mcp.tool()
    def update_trello_card(card_id: str, name: str = None, desc: str = None,
                           due: str = None, due_complete: bool = None,
                           id_list: str = None) -> dict:
        """
        Update fields on an existing Trello card.

        Args:
            card_id:      The card's 24-char Trello ID.
            name:         New card name.
            desc:         New description.
            due:          New due date (ISO 8601). Pass empty string to clear.
            due_complete: Mark due date as complete (True) or incomplete (False).
            id_list:      Move card to this list ID.
        """
        logger.info("Tool called: update_trello_card card_id=%s", card_id)
        result = ApiServiceTrelloCards(CONFIG).update_card(
            card_id=card_id, name=name, desc=desc,
            due=due, due_complete=due_complete, id_list=id_list
        )
        result = result if isinstance(result, dict) else {}
        return result

    @mcp.tool()
    def get_trello_me() -> dict:
        """Get the authenticated Trello member's profile."""
        logger.info("Tool called: get_trello_me")
        result = ApiServiceTrelloMembers(CONFIG).get_me()
        result = result if isinstance(result, dict) else {}
        logger.info("get_trello_me username=%s", result.get("username"))
        return result

    @mcp.tool()
    def get_trello_board_members(board_id: str) -> list[dict]:
        """
        Get all members of a Trello board.

        Args:
            board_id: The board's 24-char Trello ID.
        """
        logger.info("Tool called: get_trello_board_members board_id=%s", board_id)
        result = ApiServiceTrelloMembers(CONFIG).get_board_members(board_id)
        result = result if isinstance(result, list) else []
        logger.info("get_trello_board_members returned %d member(s)", len(result))
        return result
