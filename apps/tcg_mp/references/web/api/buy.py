from typing import List

from apps.tcg_mp.references.dto.listing import DtoWantToBuyListing
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.constants.payload_type import PayloadType
from core.web.services.core.decorators.deserializer import deserialized


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

    @deserialized(List[DtoWantToBuyListing], child='data.data', many=True)
    def get_want_to_buy_listings(self, product_id, foil):
        """Fetch all want-to-buy bids for the given product + foil.

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

        return self.client.execute_request(self.request.build())
