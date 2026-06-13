from typing import List, Optional

from apps.pokemon_tcg.references.dto.card import DtoPokemonTcgCard
from apps.pokemon_tcg.references.web.base_api_service import BaseApiServicePokemonTcg
from core.web.services.core.decorators.deserializer import deserialized


class ApiServicePokemonTcgCards(BaseApiServicePokemonTcg):
    """Pokemon TCG API ``/cards`` endpoint — Lucene-style card search.

    The proxy pipeline's workhorse is :meth:`search_cards_by_dex_number`,
    which builds the ``nationalPokedexNumbers:<n>`` query (optionally with a
    rarity filter) and trims the payload with ``select`` to stay light under
    rate limits.
    """

    #: API hard cap for ``pageSize``.
    MAX_PAGE_SIZE = 250

    #: Payload-trimming projection used by the proxy pipeline.
    DEFAULT_SELECT = 'id,name,number,rarity,nationalPokedexNumbers,set,images'

    def __init__(self, config, **kwargs):
        super(ApiServicePokemonTcgCards, self).__init__(config, **kwargs)

    @deserialized(List[DtoPokemonTcgCard])
    def search_cards(self,
                     q: Optional[str] = None,
                     page: Optional[int] = None,
                     page_size: Optional[int] = None,
                     order_by: Optional[str] = None,
                     select: Optional[str] = None) -> List[DtoPokemonTcgCard]:
        """Search cards with the API's Lucene-like query syntax.

        Args:
            q:         Query string, e.g. 'nationalPokedexNumbers:6 rarity:"Special Illustration Rare"'.
            page:      1-based page number.
            page_size: Results per page (max 250).
            order_by:  Sort field(s), e.g. '-set.releaseDate' (descending).
            select:    Comma-separated field projection to trim the payload.
        """
        self.request.get().set_base_uri('cards')
        params = {
            'q': q,
            'page': page,
            'pageSize': page_size,
            'orderBy': order_by,
            'select': select,
        }
        for key, value in params.items():
            if value is not None:
                self.request.add_query_string(key, value)
        return self.client.execute_request(self.request.build())

    @deserialized(DtoPokemonTcgCard, child='data')
    def get_card(self, card_id: str) -> DtoPokemonTcgCard:
        """Return a single card by its API id (e.g. 'sv3pt5-199')."""
        self.request.get().set_base_uri(f'cards/{card_id}')
        return self.client.execute_request(self.request.build())

    def search_cards_by_dex_number(self,
                                   dex_number: int,
                                   rarity: Optional[str] = None,
                                   page: Optional[int] = None,
                                   page_size: int = MAX_PAGE_SIZE,
                                   select: Optional[str] = DEFAULT_SELECT
                                   ) -> List[DtoPokemonTcgCard]:
        """Return all cards of a Pokemon by National Pokedex number.

        Args:
            dex_number: National Pokedex number, e.g. 6 for Charizard.
            rarity:     Optional exact rarity filter, e.g. 'Illustration Rare'.
                        Omit it and filter client-side when several rarities
                        are wanted — one request instead of one per rarity.
            page:       1-based page number (a dex number rarely exceeds one
                        250-card page; Pikachu is the known exception).
            page_size:  Results per page (max 250).
            select:     Field projection (default keeps the proxy-pipeline fields).
        """
        q = f'nationalPokedexNumbers:{dex_number}'
        if rarity:
            q += f' rarity:"{rarity}"'
        return self.search_cards(q=q, page=page, page_size=page_size,
                                 order_by='-set.releaseDate', select=select)
