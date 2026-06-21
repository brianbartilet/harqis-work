import logging
import re

from mcp.server.fastmcp import FastMCP
from apps.scryfall.config import CONFIG
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData

logger = logging.getLogger("harqis-mcp.scryfall")

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _resolve_card(service: ApiServiceScryfallCards, identifier: str) -> dict:
    """Resolve a card to its raw dict, accepting either a Scryfall UUID or a card name."""
    if _UUID_RE.match(identifier.strip()):
        card = service.get_card_raw(identifier.strip())
    else:
        card = service.get_card_by_name(identifier)
    return card if isinstance(card, dict) else (card.__dict__ if hasattr(card, "__dict__") else {})


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

    @mcp.tool()
    def get_scryfall_card_prices(identifier: str) -> dict:
        """Get the prices for an MTG card from Scryfall.

        Args:
            identifier: A Scryfall card UUID or a card name (fuzzy match).
        """
        logger.info("Tool called: get_scryfall_card_prices identifier=%s", identifier)
        service = ApiServiceScryfallCards(CONFIG)
        card = _resolve_card(service, identifier)
        result = {
            "name": card.get("name"),
            "set": card.get("set"),
            "collector_number": card.get("collector_number"),
            "prices": card.get("prices", {}),
        }
        logger.info("get_scryfall_card_prices name=%s", result.get("name"))
        return result

    @mcp.tool()
    def get_scryfall_card_images(identifier: str) -> dict:
        """Get the image URIs for an MTG card from Scryfall (handles double-faced cards).

        Args:
            identifier: A Scryfall card UUID or a card name (fuzzy match).
        """
        logger.info("Tool called: get_scryfall_card_images identifier=%s", identifier)
        service = ApiServiceScryfallCards(CONFIG)
        card = _resolve_card(service, identifier)
        images = card.get("image_uris")
        faces = None
        if not images and isinstance(card.get("card_faces"), list):
            faces = [
                {"name": f.get("name"), "image_uris": f.get("image_uris", {})}
                for f in card["card_faces"]
            ]
        result = {
            "name": card.get("name"),
            "image_uris": images or {},
            "card_faces": faces,
        }
        logger.info("get_scryfall_card_images name=%s", result.get("name"))
        return result

    @mcp.tool()
    def get_scryfall_card_versions(identifier: str) -> list[dict]:
        """Get all prints/versions of an MTG card from Scryfall.

        Args:
            identifier: A card name, or a Scryfall card UUID (resolved to its name first).
        """
        logger.info("Tool called: get_scryfall_card_versions identifier=%s", identifier)
        service = ApiServiceScryfallCards(CONFIG)
        name = identifier
        if _UUID_RE.match(identifier.strip()):
            card = _resolve_card(service, identifier)
            name = card.get("name", identifier)
        versions = service.get_card_versions(name)
        result = versions if isinstance(versions, list) else []
        logger.info("get_scryfall_card_versions returned %d version(s) for %s", len(result), name)
        return result

    @mcp.tool()
    def query_scryfall_bulk(query: str, field: str = "name", bulk_data_type: str = "default-cards",
                            limit: int = 50, force_download: bool = False) -> list[dict]:
        """Download (or reuse) the latest Scryfall bulk data file and return matching cards.

        Streams the large bulk file and returns only cards whose `field` contains `query`
        (case-insensitive substring) — never dumps the whole file.

        Args:
            query: Substring to match.
            field: Card field to match against (default 'name').
            bulk_data_type: Bulk type — 'default-cards' (default), 'oracle-cards', or 'all-cards' (huge).
            limit: Maximum number of cards to return (default 50).
            force_download: Re-download even if today's file already exists locally.
        """
        logger.info("Tool called: query_scryfall_bulk query=%s field=%s type=%s", query, field, bulk_data_type)
        service = ApiServiceScryfallBulkData(CONFIG)
        results = service.query_bulk(query, bulk_data_type=bulk_data_type, field=field,
                                     limit=limit, force_download=force_download)
        output = results if isinstance(results, list) else []
        logger.info("query_scryfall_bulk returned %d card(s)", len(output))
        return output
