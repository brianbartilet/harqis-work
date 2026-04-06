import logging

from mcp.server.fastmcp import FastMCP
from apps.scryfall.config import CONFIG
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData

logger = logging.getLogger("harqis-mcp.scryfall")


def register_scryfall_tools(mcp: FastMCP):

    @mcp.tool()
    def get_scryfall_card(card_guid: str) -> dict:
        """Get full metadata for an MTG card from Scryfall by its UUID.

        Args:
            card_guid: Scryfall card UUID (e.g. 'e3285e6b-3e79-4d7c-bf96-d920f973b122')
        """
        logger.info("Tool called: get_scryfall_card card_guid=%s", card_guid)
        service = ApiServiceScryfallCards(CONFIG)
        card = service.get_card_metadata(card_guid)
        result = card.__dict__ if hasattr(card, "__dict__") else (card if isinstance(card, dict) else {})
        logger.info("get_scryfall_card name=%s", result.get("name", "?") if isinstance(result, dict) else "?")
        return result

    @mcp.tool()
    def get_scryfall_bulk_data_info() -> list[dict]:
        """Get metadata about available Scryfall bulk data files (all-cards, oracle-cards, etc.).

        Returns a list of bulk data objects describing available downloads — does NOT download the files.
        """
        logger.info("Tool called: get_scryfall_bulk_data_info")
        service = ApiServiceScryfallBulkData(CONFIG)
        data = service.get_card_data_bulk()
        result = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        logger.info("get_scryfall_bulk_data_info returned %d bulk type(s)", len(result))
        return result
