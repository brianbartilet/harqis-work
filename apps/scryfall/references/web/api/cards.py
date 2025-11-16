import time

from apps.scryfall.references.dto.card import DtoScryFallCard
from apps.scryfall.references.web.base_api_service import BaseApiServiceAppScryfallMtg

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceScryfallCards(BaseApiServiceAppScryfallMtg):

    def __init__(self, config, **kwargs):
        super(ApiServiceScryfallCards, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('cards')

    @deserialized(DtoScryFallCard)
    def get_card_metadata(self, card_guid: str, rate_limit_delay=5):
        self.request.get() \
            .add_uri_parameter(card_guid) \
            .add_query_string('format', 'json') \
            .add_query_string('pretty', 'true')

        response = self.client.execute_request(self.request.build(), rate_limit_delay=rate_limit_delay)

        return response
