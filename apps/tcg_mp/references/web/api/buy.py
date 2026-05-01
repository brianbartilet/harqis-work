from dataclasses import fields
from typing import List

from apps.tcg_mp.references.dto.listing import DtoWantToBuyListing
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.constants.payload_type import PayloadType


class ApiServiceTcgMpBuy(BaseApiServiceAppTcgMp):
    """Buyer-side endpoints under `/buy`.

    `listed_item_filter` returns every active want-to-buy bid placed by other
    users for a specific product + foil combination. Pair with the want-to-buy
    cart in `cart.py` to convert a bid into a sell-cart entry.
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpBuy, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('buy')

    def get_want_to_buy_listings(self, product_id, foil) -> List[DtoWantToBuyListing]:
        """Fetch all want-to-buy bids for the given product + foil.

        The marketplace's response shape is:
            {"status": 200, "data": {"message": "", "data": [...] | "" }, "meta": {...}}
        On no-results the inner `data.data` is sometimes returned as an empty
        string instead of an empty list, which broke the framework's typed
        deserializer (`@deserialized`). We parse the inner list manually here
        so the worker always receives an iterable.

        Args:
            product_id: TCG MP product id (the same `product_id` returned on
                        `DtoListingItem`).
            foil:       String "0" / "1" or int 0 / 1 — sent as a string to
                        match the marketplace's payload contract.

        Returns:
            List[DtoWantToBuyListing] — empty list when no buyers are bidding.
        """
        payload = {
            'product_id': str(product_id),
            'foil': str(foil),
        }
        self.request.post() \
            .add_uri_parameter('listed_item_filter') \
            .add_payload(payload, PayloadType.DICT)

        response = self.client.execute_request(self.request.build())
        return _parse_want_to_buy_listings(response)


_DTO_FIELDS = {f.name for f in fields(DtoWantToBuyListing)}


def _parse_want_to_buy_listings(response) -> List[DtoWantToBuyListing]:
    """Extract the bid list from a `buy/listed_item_filter` response.

    Tolerates the no-results case where `data.data` is `""` instead of `[]`,
    and the case where the framework already unwrapped one layer.
    """
    body = getattr(response, "data", response)
    if isinstance(body, dict):
        body = body.get("data", body)
    if not body or isinstance(body, str):
        return []
    if not isinstance(body, list):
        return []
    return [_to_dto(item) for item in body if isinstance(item, dict)]


def _to_dto(item: dict) -> DtoWantToBuyListing:
    """Build a DTO from an arbitrary item dict, ignoring unknown keys."""
    kwargs = {k: v for k, v in item.items() if k in _DTO_FIELDS}
    return DtoWantToBuyListing(**kwargs)
