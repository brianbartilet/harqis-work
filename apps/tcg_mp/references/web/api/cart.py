from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.constants.payload_type import PayloadType
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTcgMpUserViewCart(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpUserViewCart, self).__init__(config, **kwargs)
        self.user_id = config.app_data['user_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('cart')

    @deserialized(dict, child='data.data.0', many=True)
    def get_account_summary(self):
        self.request.get() \
            .add_uri_parameter('summary')
        return self.client.execute_request(self.request.build())


class ApiServiceTcgMpWantToBuyCart(BaseApiServiceAppTcgMp):
    """The seller's "sell cart" — bids the seller has accepted and queued
    for fulfilment. Backed by the marketplace's `/want_to_buy/cart` namespace.

    `add` converts a buyer's want-to-buy bid (the `id` from `ApiServiceTcgMpBuy
    .get_want_to_buy_listings`) into a sell-cart entry. The seller fulfils the
    cart manually from https://thetcgmarketplace.com/sellcart.
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpWantToBuyCart, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        # base_uri is reset per method because this service spans two paths
        # under the same host (`/want_to_buy/cart/add`, future `/want_to_buy/cart`).
        self.request.set_base_uri('want_to_buy')

    @deserialized(dict, child='data')
    def add_to_sell_cart(self, listing_id, qty=1):
        """Accept a buyer's want-to-buy bid and queue it in the seller's sell cart.

        Args:
            listing_id: The `id` field on a `DtoWantToBuyListing` returned by
                        `ApiServiceTcgMpBuy.get_want_to_buy_listings`. This is
                        the want-to-buy record id, NOT the seller's listing id.
            qty:        Number of copies the seller agrees to fulfil from the
                        buyer's outstanding bid quantity.

        Returns:
            The `data` field from the marketplace response.
        """
        # Re-set base each call in case another method shifted it.
        self.request.set_base_uri('want_to_buy')
        payload = {
            'listing_id': listing_id,
            'qty': qty,
        }
        self.request.post() \
            .add_uri_parameter('cart') \
            .add_uri_parameter('add') \
            .add_payload(payload, PayloadType.DICT)

        return self.client.execute_request(self.request.build())

