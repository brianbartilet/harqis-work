import logging

from mcp.server.fastmcp import FastMCP
from apps.echo_mtg.config import CONFIG
from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.references.web.api.earnings import ApiServiceEchoMTGEarnings
from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes

logger = logging.getLogger("harqis-mcp.echo_mtg")


def register_echo_mtg_tools(mcp: FastMCP):

    @mcp.tool()
    def get_echo_mtg_portfolio_stats() -> dict:
        """Get quick portfolio statistics from Echo MTG including total value and collection size."""
        logger.info("Tool called: get_echo_mtg_portfolio_stats")
        service = ApiServiceEchoMTGInventory(CONFIG)
        stats = service.get_quick_stats()
        result = stats.__dict__ if hasattr(stats, "__dict__") else (stats if isinstance(stats, dict) else {})
        logger.info("get_echo_mtg_portfolio_stats done")
        return result

    @mcp.tool()
    def get_echo_mtg_collection(limit: int = 100, tradable_only: int = 0) -> list[dict]:
        """Get the Echo MTG card collection inventory.

        Args:
            limit: Maximum number of items to return (default 100, max 10000)
            tradable_only: Set to 1 to return only tradable cards, 0 for all (default 0)
        """
        logger.info("Tool called: get_echo_mtg_collection limit=%d tradable_only=%d", limit, tradable_only)
        service = ApiServiceEchoMTGInventory(CONFIG)
        items = service.get_collection(start=0, limit=limit, tradable_only=tradable_only)
        result = items if isinstance(items, list) else []
        logger.info("get_echo_mtg_collection returned %d item(s)", len(result))
        return result

    @mcp.tool()
    def search_echo_mtg_card(emid: str, tradable_only: int = 1) -> list[dict]:
        """Search the Echo MTG inventory for a card by its Echo MTG ID (emid).

        Args:
            emid: Echo MTG card ID to search for
            tradable_only: Set to 1 to return only tradable copies (default 1), 0 for all
        """
        logger.info("Tool called: search_echo_mtg_card emid=%s tradable_only=%d", emid, tradable_only)
        service = ApiServiceEchoMTGInventory(CONFIG)
        results = service.search_card(emid, tradable_only=tradable_only)
        output = results if isinstance(results, list) else []
        logger.info("search_echo_mtg_card returned %d result(s)", len(output))
        return output

    @mcp.tool()
    def remove_echo_mtg_item(inventory_id: str) -> dict:
        """Remove (delete) an item from the Echo MTG inventory.

        Destructive: the inventory record is deleted. Use the inventory_id from a
        collection/search result.

        Args:
            inventory_id: The inventory record ID to delete.
        """
        logger.info("Tool called: remove_echo_mtg_item inventory_id=%s", inventory_id)
        service = ApiServiceEchoMTGInventory(CONFIG)
        result = service.remove_item(inventory_id)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("remove_echo_mtg_item done inventory_id=%s", inventory_id)
        return output

    @mcp.tool()
    def mark_echo_mtg_sold(emid: str, acquired_price: float, sold_price: float, foil: int = 0) -> dict:
        """Record an Echo MTG card as sold (adds it to earnings).

        Args:
            emid: Echo MTG card ID of the card sold.
            acquired_price: Original purchase price.
            sold_price: Sale price.
            foil: 0 for non-foil, 1 for foil (default 0).
        """
        logger.info("Tool called: mark_echo_mtg_sold emid=%s sold_price=%s", emid, sold_price)
        service = ApiServiceEchoMTGEarnings(CONFIG)
        result = service.add_sale(emid, acquired_price, sold_price, foil=foil)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("mark_echo_mtg_sold done emid=%s", emid)
        return output

    @mcp.tool()
    def update_echo_mtg_sold_price(earnings_id: str, value: float) -> dict:
        """Update the sold price of an existing Echo MTG earnings entry.

        Args:
            earnings_id: The earnings entry ID (returned by mark_echo_mtg_sold).
            value: New sold price.
        """
        logger.info("Tool called: update_echo_mtg_sold_price earnings_id=%s value=%s", earnings_id, value)
        service = ApiServiceEchoMTGEarnings(CONFIG)
        result = service.update_sold_price(earnings_id, value)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("update_echo_mtg_sold_price done earnings_id=%s", earnings_id)
        return output

    @mcp.tool()
    def update_echo_mtg_sold_date(earnings_id: str, value: str) -> dict:
        """Update the sold date of an existing Echo MTG earnings entry.

        Args:
            earnings_id: The earnings entry ID (returned by mark_echo_mtg_sold).
            value: New sold date in 'YYYY-MM-DD' format.
        """
        logger.info("Tool called: update_echo_mtg_sold_date earnings_id=%s value=%s", earnings_id, value)
        service = ApiServiceEchoMTGEarnings(CONFIG)
        result = service.update_sold_date(earnings_id, value)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("update_echo_mtg_sold_date done earnings_id=%s", earnings_id)
        return output

    @mcp.tool()
    def get_echo_mtg_note(note_id: str) -> dict:
        """Get a note by its ID from Echo MTG.

        Args:
            note_id: The note ID.
        """
        logger.info("Tool called: get_echo_mtg_note note_id=%s", note_id)
        service = ApiServiceEchoMTGNotes(CONFIG)
        result = service.get_note(note_id)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("get_echo_mtg_note done note_id=%s", note_id)
        return output

    @mcp.tool()
    def create_echo_mtg_note(inventory_id: str, note: str) -> dict:
        """Create a note attached to an Echo MTG inventory item.

        Args:
            inventory_id: The inventory item ID to attach the note to.
            note: The note text.
        """
        logger.info("Tool called: create_echo_mtg_note inventory_id=%s", inventory_id)
        service = ApiServiceEchoMTGNotes(CONFIG)
        result = service.create_note(inventory_id, note)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("create_echo_mtg_note done inventory_id=%s", inventory_id)
        return output

    @mcp.tool()
    def update_echo_mtg_note(note_id: str, note: str) -> dict:
        """Update the text of an existing Echo MTG note.

        Args:
            note_id: The note ID to update.
            note: The new note text.
        """
        logger.info("Tool called: update_echo_mtg_note note_id=%s", note_id)
        service = ApiServiceEchoMTGNotes(CONFIG)
        result = service.update_note(note_id, note)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("update_echo_mtg_note done note_id=%s", note_id)
        return output

    @mcp.tool()
    def delete_echo_mtg_note(note_id: str) -> dict:
        """Delete a note from an Echo MTG inventory item.

        Args:
            note_id: The note ID to delete.
        """
        logger.info("Tool called: delete_echo_mtg_note note_id=%s", note_id)
        service = ApiServiceEchoMTGNotes(CONFIG)
        result = service.delete_note(note_id)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("delete_echo_mtg_note done note_id=%s", note_id)
        return output
