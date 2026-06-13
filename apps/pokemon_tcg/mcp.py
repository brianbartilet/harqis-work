import logging

from mcp.server.fastmcp import FastMCP
from apps.pokemon_tcg.config import CONFIG
from apps.pokemon_tcg.references.web.api.cards import ApiServicePokemonTcgCards
from apps.pokemon_tcg.references.web.api.rarities import ApiServicePokemonTcgRarities
from apps.pokemon_tcg.references.web.api.sets import ApiServicePokemonTcgSets

logger = logging.getLogger("harqis-mcp.pokemon_tcg")


def _to_dicts(result) -> list[dict]:
    """Normalise a DTO / list-of-DTOs result into a list of plain dicts."""
    if result is None:
        return []
    if not isinstance(result, list):
        result = [result]
    return [r.__dict__ if hasattr(r, "__dict__") else r for r in result if r is not None]


def register_pokemon_tcg_tools(mcp: FastMCP):

    @mcp.tool()
    def search_pokemon_tcg_cards(q: str, page: int = None, page_size: int = 20,
                                 order_by: str = None, select: str = None) -> list[dict]:
        """Search Pokemon TCG cards with the API's Lucene-like query syntax.

        Args:
            q:         Query string, e.g. 'name:charizard rarity:"Special Illustration Rare"'
                       or 'nationalPokedexNumbers:6'.
            page:      1-based page number.
            page_size: Results per page (default 20, max 250).
            order_by:  Sort field(s), e.g. '-set.releaseDate' for newest first.
            select:    Comma-separated field projection to trim the payload.
        """
        logger.info("Tool called: search_pokemon_tcg_cards q=%s page=%s", q, page)
        service = ApiServicePokemonTcgCards(CONFIG)
        result = _to_dicts(service.search_cards(q=q, page=page, page_size=page_size,
                                                order_by=order_by, select=select))
        logger.info("search_pokemon_tcg_cards returned %d card(s)", len(result))
        return result

    @mcp.tool()
    def get_pokemon_tcg_cards_by_dex(dex_number: int, rarity: str = None) -> list[dict]:
        """List a Pokemon's TCG printings by National Pokedex number, newest set first.

        Args:
            dex_number: National Pokedex number (e.g. 6 for Charizard).
            rarity:     Optional exact rarity filter — use the strings from
                        list_pokemon_tcg_rarities (e.g. 'Illustration Rare');
                        there is no 'Full Art' rarity in the API.
        """
        logger.info("Tool called: get_pokemon_tcg_cards_by_dex dex=%s rarity=%s", dex_number, rarity)
        service = ApiServicePokemonTcgCards(CONFIG)
        result = _to_dicts(service.search_cards_by_dex_number(dex_number, rarity=rarity))
        logger.info("get_pokemon_tcg_cards_by_dex returned %d card(s)", len(result))
        return result

    @mcp.tool()
    def list_pokemon_tcg_sets(q: str = None, order_by: str = "-releaseDate") -> list[dict]:
        """List Pokemon TCG expansion sets (newest first by default).

        Args:
            q:        Optional set query, e.g. 'series:"Scarlet & Violet"'.
            order_by: Sort field(s) (default '-releaseDate').
        """
        logger.info("Tool called: list_pokemon_tcg_sets q=%s", q)
        service = ApiServicePokemonTcgSets(CONFIG)
        result = _to_dicts(service.list_sets(q=q, order_by=order_by))
        logger.info("list_pokemon_tcg_sets returned %d set(s)", len(result))
        return result

    @mcp.tool()
    def list_pokemon_tcg_rarities() -> list[str]:
        """List every rarity string the Pokemon TCG API knows (e.g. 'Illustration Rare',
        'Special Illustration Rare', 'Rare Ultra', 'Hyper Rare'). Use these exact
        strings when filtering — the API has no literal 'Full Art' rarity."""
        logger.info("Tool called: list_pokemon_tcg_rarities")
        service = ApiServicePokemonTcgRarities(CONFIG)
        result = service.list_rarities()
        result = result if isinstance(result, list) else []
        logger.info("list_pokemon_tcg_rarities returned %d rarities", len(result))
        return result
