import logging

from mcp.server.fastmcp import FastMCP
from apps.justtcg.config import CONFIG
from apps.justtcg.references.web.api.games import ApiServiceJusttcgGames
from apps.justtcg.references.web.api.sets import ApiServiceJusttcgSets
from apps.justtcg.references.web.api.cards import ApiServiceJusttcgCards

logger = logging.getLogger("harqis-mcp.justtcg")


def _to_dicts(result) -> list[dict]:
    """Normalise a DTO / list-of-DTOs result into a list of plain dicts."""
    if result is None:
        return []
    if not isinstance(result, list):
        result = [result]
    return [r.__dict__ if hasattr(r, "__dict__") else r for r in result if r is not None]


def register_justtcg_tools(mcp: FastMCP):

    @mcp.tool()
    def list_justtcg_games() -> list[dict]:
        """List all trading-card games supported by JustTCG (Pokémon, Magic, Yu-Gi-Oh!,
        Lorcana, One Piece, Digimon, Union Arena, …) with aggregate value stats.

        Each game's `id` is the slug used as the `game` argument elsewhere.
        """
        logger.info("Tool called: list_justtcg_games")
        service = ApiServiceJusttcgGames(CONFIG)
        result = _to_dicts(service.list_games())
        logger.info("list_justtcg_games returned %d game(s)", len(result))
        return result

    @mcp.tool()
    def list_justtcg_sets(game: str = None, q: str = None,
                          limit: int = None, offset: int = None) -> list[dict]:
        """List card sets, optionally filtered by game and/or name search.

        Args:
            game:   Restrict to a single game id (e.g. 'pokemon', 'mtg').
            q:      Search sets by name.
            limit:  Page size.
            offset: Pagination offset.
        """
        logger.info("Tool called: list_justtcg_sets game=%s q=%s", game, q)
        service = ApiServiceJusttcgSets(CONFIG)
        result = _to_dicts(service.list_sets(game=game, q=q, limit=limit, offset=offset))
        logger.info("list_justtcg_sets returned %d set(s)", len(result))
        return result

    @mcp.tool()
    def get_justtcg_card(card_id: str = None, variant_id: str = None,
                         tcgplayer_id: str = None, condition: str = None,
                         printing: str = None) -> list[dict]:
        """Look up a single card and its priced variants by one identifier.

        Provide exactly one of `variant_id`, `tcgplayer_id`, or `card_id`
        (precedence: variant_id > tcgplayer_id > card_id). Pricing lives in each
        returned card's `variants` array.

        Args:
            card_id:      JustTCG card slug (e.g. 'pokemon-base-set-shadowless-charizard-holo-rare').
            variant_id:   Exact variant id — fastest, single result.
            tcgplayer_id: TCGplayer product id.
            condition:    Filter variants by condition (e.g. 'NM'). Ignored if variant_id is set.
            printing:     Filter variants by printing (e.g. 'Foil'). Ignored if variant_id is set.
        """
        logger.info("Tool called: get_justtcg_card card_id=%s variant_id=%s tcgplayer_id=%s",
                    card_id, variant_id, tcgplayer_id)
        service = ApiServiceJusttcgCards(CONFIG)
        result = _to_dicts(service.get_card(
            card_id=card_id, variant_id=variant_id, tcgplayer_id=tcgplayer_id,
            condition=condition, printing=printing,
        ))
        logger.info("get_justtcg_card returned %d card(s)", len(result))
        return result

    @mcp.tool()
    def search_justtcg_cards(q: str = None, game: str = None, set_id: str = None,
                             condition: str = None, printing: str = None,
                             order_by: str = None, order: str = None,
                             limit: int = 20, offset: int = None) -> list[dict]:
        """Search / browse cards with filters, sorted for pricing analytics.

        The pricing-analytics entry point: set `order_by` to a price-movement
        window and `order='desc'` to surface the biggest movers in a game/set.

        Args:
            q:         Free-text search (card name).
            game:      Restrict to a game id (e.g. 'pokemon').
            set_id:    Restrict to a set id.
            condition: Filter variants by condition.
            printing:  Filter variants by printing.
            order_by:  Sort key — 'price', '24h', '7d', or '30d' (price-change window).
            order:     'desc' (default) or 'asc'.
            limit:     Page size (default 20).
            offset:    Pagination offset.
        """
        logger.info("Tool called: search_justtcg_cards q=%s game=%s order_by=%s", q, game, order_by)
        service = ApiServiceJusttcgCards(CONFIG)
        result = _to_dicts(service.search_cards(
            q=q, game=game, set=set_id, condition=condition, printing=printing,
            order_by=order_by, order=order, limit=limit, offset=offset,
        ))
        logger.info("search_justtcg_cards returned %d card(s)", len(result))
        return result

    @mcp.tool()
    def batch_justtcg_cards(items: list[dict]) -> list[dict]:
        """Look up many cards/variants in one batch request (efficient bulk pricing).

        Args:
            items: A list of lookup objects (plan cap: 20 free / 100 starter & pro /
                   200 enterprise). Each object carries one identifier and optional
                   per-item filters, e.g. {"tcgplayerId": "106999"} or
                   {"cardId": "pokemon-...", "condition": "NM", "printing": "Foil"}.
        """
        logger.info("Tool called: batch_justtcg_cards items=%d", len(items) if isinstance(items, list) else 0)
        service = ApiServiceJusttcgCards(CONFIG)
        payload = items if isinstance(items, list) else []
        result = _to_dicts(service.batch_cards(payload))
        logger.info("batch_justtcg_cards returned %d card(s)", len(result))
        return result
