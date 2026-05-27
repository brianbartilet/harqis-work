from typing import Any, Dict, List, Optional

from apps.justtcg.references.dto.card import DtoJusttcgCard
from apps.justtcg.references.web.base_api_service import BaseApiServiceJusttcg
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceJusttcgCards(BaseApiServiceJusttcg):
    """JustTCG ``/cards`` endpoint — card lookup, search, and batch pricing.

    All three methods return a list of :class:`DtoJusttcgCard`; pricing lives in
    each card's ``variants``. ``search_cards`` is the analytics workhorse — sort
    by a price-movement window via ``order_by`` ('24h' | '7d' | '30d') to surface
    the biggest movers.
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceJusttcgCards, self).__init__(config, **kwargs)

    @deserialized(List[DtoJusttcgCard])
    def get_card(self,
                 card_id: Optional[str] = None,
                 variant_id: Optional[str] = None,
                 tcgplayer_id: Optional[str] = None,
                 mtgjson_id: Optional[str] = None,
                 scryfall_id: Optional[str] = None,
                 tcgplayer_sku_id: Optional[str] = None,
                 condition: Optional[str] = None,
                 printing: Optional[str] = None) -> List[DtoJusttcgCard]:
        """Look up a card by one of its identifiers; returns matching card(s)
        with their priced variants.

        Provide one identifier (server precedence, fastest first):
        ``variant_id`` > ``tcgplayer_sku_id`` > ``tcgplayer_id`` >
        ``mtgjson_id`` > ``scryfall_id`` > ``card_id``.

        Args:
            card_id:          JustTCG card slug (e.g. 'pokemon-base-set-shadowless-charizard-holo-rare').
            variant_id:       Exact variant id — fastest, single result.
            tcgplayer_id:     TCGplayer product id.
            mtgjson_id:       MTGJSON UUID.
            scryfall_id:      Scryfall UUID.
            tcgplayer_sku_id: TCGplayer SKU id (variant-level).
            condition:        Filter variants by condition (e.g. 'NM').
                              Ignored when variant_id/tcgplayer_sku_id is set.
            printing:         Filter variants by printing (e.g. 'Foil').
                              Ignored when variant_id/tcgplayer_sku_id is set.
        """
        self.request.get().set_base_uri('cards')
        identifiers = {
            'variantId': variant_id,
            'tcgplayerSkuId': tcgplayer_sku_id,
            'tcgplayerId': tcgplayer_id,
            'mtgjsonId': mtgjson_id,
            'scryfallId': scryfall_id,
            'cardId': card_id,
        }
        for key, value in identifiers.items():
            if value:
                self.request.add_query_string(key, value)
        if condition:
            self.request.add_query_string('condition', condition)
        if printing:
            self.request.add_query_string('printing', printing)
        return self.client.execute_request(self.request.build())

    @deserialized(List[DtoJusttcgCard])
    def search_cards(self,
                     q: Optional[str] = None,
                     game: Optional[str] = None,
                     set: Optional[str] = None,
                     condition: Optional[str] = None,
                     printing: Optional[str] = None,
                     order_by: Optional[str] = None,
                     order: Optional[str] = None,
                     limit: Optional[int] = None,
                     offset: Optional[int] = None) -> List[DtoJusttcgCard]:
        """Search / browse cards with filters, sorted for pricing analytics.

        Args:
            q:         Free-text search (card name).
            game:      Restrict to a game id (e.g. 'pokemon').
            set:       Restrict to a set id.
            condition: Filter variants by condition.
            printing:  Filter variants by printing.
            order_by:  Sort key — 'price', '24h', '7d', or '30d' (price-change
                       window). Use with order='desc' for "biggest movers".
            order:     'desc' (default) or 'asc'.
            limit:     Page size.
            offset:    Pagination offset.
        """
        self.request.get().set_base_uri('cards')
        params = {
            'q': q,
            'game': game,
            'set': set,
            'condition': condition,
            'printing': printing,
            'orderBy': order_by,
            'order': order,
            'limit': limit,
            'offset': offset,
        }
        for key, value in params.items():
            if value is not None:
                self.request.add_query_string(key, value)
        return self.client.execute_request(self.request.build())

    @deserialized(List[DtoJusttcgCard])
    def batch_cards(self, items: List[Dict[str, Any]]) -> List[DtoJusttcgCard]:
        """Look up many cards/variants in a single POST (batch pricing).

        Args:
            items: A list of lookup objects (plan-dependent cap: 20 free /
                   100 starter & pro / 200 enterprise). Each object carries one
                   identifier and optional per-item filters, e.g.
                   ``{'tcgplayerId': '106999'}`` or
                   ``{'cardId': 'pokemon-...', 'condition': 'NM', 'printing': 'Foil'}``.
        """
        self.request.post().set_base_uri('cards').add_json_payload(items)
        return self.client.execute_request(self.request.build())
