import logging

from mcp.server.fastmcp import FastMCP
from apps.tcg_mp.config import CONFIG
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView
from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish
from apps.tcg_mp.references.dto.order import EnumTcgOrderStatus

logger = logging.getLogger("harqis-mcp.tcg_mp")


def register_tcg_mp_tools(mcp: FastMCP):

    @mcp.tool()
    def search_tcg_card(card_name: str, page: int = 1, items: int = 20) -> list[dict]:
        """Search for MTG cards on the TCG Marketplace by name.

        Args:
            card_name: Card name to search for
            page: Page number (default 1)
            items: Number of results per page (default 20, max 100)
        """
        logger.info("Tool called: search_tcg_card card_name=%s page=%d items=%d", card_name, page, items)
        service = ApiServiceTcgMpProducts(CONFIG)
        results = service.search_card(card_name, page=page, items=items)
        output = results if isinstance(results, list) else []
        serialized = [r.__dict__ if hasattr(r, "__dict__") else r for r in output]
        logger.info("search_tcg_card returned %d result(s)", len(serialized))
        return serialized

    @mcp.tool()
    def get_tcg_orders(status: str = "PENDING_DROP_OFF") -> list[dict]:
        """Get TCG Marketplace orders filtered by status.

        Args:
            status: Order status — one of ALL, PENDING_DROP_OFF, SHIPPED, COMPLETED,
                    CANCELLED, NOT_RECEIVED, DROPPED, ARRIVED_BRANCH, PICKED_UP, PENDING_PAYMENT.
                    Defaults to PENDING_DROP_OFF.
        """
        logger.info("Tool called: get_tcg_orders status=%s", status)
        try:
            status_enum = EnumTcgOrderStatus[status.upper()]
        except KeyError:
            status_enum = EnumTcgOrderStatus.PENDING_DROP_OFF

        service = ApiServiceTcgMpOrder(CONFIG)
        orders = service.get_orders(by_status=status_enum)
        output = orders if isinstance(orders, list) else []
        serialized = [o.__dict__ if hasattr(o, "__dict__") else o for o in output]
        logger.info("get_tcg_orders returned %d order group(s)", len(serialized))
        return serialized

    @mcp.tool()
    def get_tcg_order_detail(order_id: str) -> dict:
        """Get detailed information for a specific TCG Marketplace order.

        Args:
            order_id: The order ID string
        """
        logger.info("Tool called: get_tcg_order_detail order_id=%s", order_id)
        service = ApiServiceTcgMpOrder(CONFIG)
        detail = service.get_order_detail(order_id)
        result = detail if isinstance(detail, dict) else (detail.__dict__ if hasattr(detail, "__dict__") else {})
        logger.info("get_tcg_order_detail done order_id=%s", order_id)
        return result

    @mcp.tool()
    def get_tcg_listings() -> list[dict]:
        """Get all active card listings for the configured TCG Marketplace user."""
        logger.info("Tool called: get_tcg_listings")
        service = ApiServiceTcgMpUserView(CONFIG)
        listings = service.get_listings()
        output = listings if isinstance(listings, list) else []
        serialized = [item.__dict__ if hasattr(item, "__dict__") else item for item in output]
        logger.info("get_tcg_listings returned %d listing(s)", len(serialized))
        return serialized

    @mcp.tool()
    def create_tcg_listing(product_id: int, price: float, quantity: int = 1, foil: int = 0,
                           language: str = "EN", condition: str = "NM", signed: int = 0) -> dict:
        """Create (publish) a new card listing on the TCG Marketplace.

        Args:
            product_id: The marketplace product ID to list (from search_tcg_card results).
            price: Listing price.
            quantity: Number of copies (default 1).
            foil: 0 for non-foil, 1 for foil (default 0).
            language: Card language code (default 'EN').
            condition: Card condition — e.g. NM, LP, MP, HP, DM (default 'NM').
            signed: 0 for unsigned, 1 for signed (default 0).
        """
        logger.info("Tool called: create_tcg_listing product_id=%s price=%s qty=%s", product_id, price, quantity)
        service = ApiServiceTcgMpPublish(CONFIG)
        result = service.add_listing(product_id, price, quantity=quantity, foil=foil,
                                     language=language, condition=condition, signed=signed)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("create_tcg_listing done product_id=%s", product_id)
        return output

    @mcp.tool()
    def remove_tcg_listings(listing_ids: list[int]) -> dict:
        """Remove (delete) one or more listings from the TCG Marketplace.

        Destructive: the listings are deleted. Pass the listing IDs from get_tcg_listings.

        Args:
            listing_ids: A list of listing IDs to remove.
        """
        logger.info("Tool called: remove_tcg_listings ids=%s", listing_ids)
        service = ApiServiceTcgMpPublish(CONFIG)
        result = service.remove_listings(listing_ids)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("remove_tcg_listings done count=%d", len(listing_ids))
        return output

    @mcp.tool()
    def download_tcg_order_qr(order_id: str) -> dict:
        """Download an order's QR code image to disk and return its URL and local path.

        Args:
            order_id: The order ID string.
        """
        logger.info("Tool called: download_tcg_order_qr order_id=%s", order_id)
        service = ApiServiceTcgMpOrder(CONFIG)
        result = service.download_order_qr(order_id)
        logger.info("download_tcg_order_qr saved order_id=%s path=%s", order_id, result.get("file_path"))
        return result
