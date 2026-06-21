from apps.echo_mtg.references.web.base_api_service import BaseApiServiceAppEchoMtg

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceEchoMTGEarnings(BaseApiServiceAppEchoMtg):
    """Echo MTG earnings (sales) API — records a card as sold and edits sold price/date.

    Mirrors the documented endpoints at https://www.echomtg.com/api/ under ``earnings/``.
    Recording a sale moves the card out of the active portfolio value and into earnings.
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceEchoMTGEarnings, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('earnings')

    @deserialized(dict)
    def add_sale(self, emid, acquired_price, sold_price, foil=0):
        """Record a card as sold (adds it to earnings).

        Args:
            emid: Echo MTG card ID of the card sold.
            acquired_price: Original purchase price.
            sold_price: Sale price.
            foil: 0 for non-foil, 1 for foil.
        """
        payload = {
            'emid': emid,
            'acquired_price': str(acquired_price),
            'sold_price': str(sold_price),
            'foil': foil,
        }

        self.request.post() \
            .add_uri_parameter('add') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_sold_price(self, earnings_id, value):
        """Update the sold price of an existing earnings entry.

        Args:
            earnings_id: The earnings entry ID returned by ``add_sale``.
            value: New sold price.
        """
        payload = {
            'id': earnings_id,
            'value': value,
        }

        self.request.post() \
            .add_uri_parameter('update-sold-price') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_sold_date(self, earnings_id, value):
        """Update the sold date of an existing earnings entry.

        Args:
            earnings_id: The earnings entry ID returned by ``add_sale``.
            value: New sold date in ``YYYY-MM-DD`` format.
        """
        payload = {
            'id': earnings_id,
            'value': value,
        }

        self.request.post() \
            .add_uri_parameter('update-sold-date') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())
