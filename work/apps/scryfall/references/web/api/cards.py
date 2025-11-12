from work.apps.scryfall.references.dto.card import DtoScryFallCard
from work.apps.scryfall.references.web.base_api_service import BaseApiServiceAppScryfallMtg

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceScryfallCards(BaseApiServiceAppScryfallMtg):

    def __init__(self, config, **kwargs):
        super(ApiServiceScryfallCards, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .add_uri_parameter('cards')

    @deserialized(DtoScryFallCard)
    def get_card_metadata(self, card_guid: str):
        self.request.get()\
            .add_uri_parameter(card_guid)
        response = self.client.execute_request(self.request.build())

        return response
