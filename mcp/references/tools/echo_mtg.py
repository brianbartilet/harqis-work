import logging

from mcp.server.fastmcp import FastMCP
from apps.echo_mtg.config import CONFIG
from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory

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
