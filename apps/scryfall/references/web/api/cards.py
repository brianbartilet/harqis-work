from typing import List

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

    @deserialized(dict)
    def get_card_raw(self, card_guid: str, rate_limit_delay=5):
        """Get the full raw card payload by Scryfall UUID (keeps nested blobs like card_faces)."""
        self.request.get() \
            .add_uri_parameter(card_guid) \
            .add_query_string('format', 'json')

        return self.client.execute_request(self.request.build(), rate_limit_delay=rate_limit_delay)

    @deserialized(dict)
    def get_card_by_name(self, name: str, set_code: str = None, fuzzy: bool = True, rate_limit_delay=5):
        """Resolve a card by name via the Scryfall ``cards/named`` endpoint.

        Args:
            name: Card name.
            set_code: Optional set code to disambiguate the print.
            fuzzy: Use fuzzy matching (default) or exact matching.
        """
        self.request.get() \
            .add_uri_parameter('named') \
            .add_query_string('fuzzy' if fuzzy else 'exact', name) \
            .add_query_string('format', 'json')
        if set_code:
            self.request.add_query_string('set', set_code)

        return self.client.execute_request(self.request.build(), rate_limit_delay=rate_limit_delay)

    @deserialized(List[dict], child='data')
    def get_card_versions(self, name: str, rate_limit_delay=5):
        """Get all prints/versions of a card by name via ``cards/search?unique=prints``."""
        self.request.get() \
            .add_uri_parameter('search') \
            .add_query_string('q', f'!"{name}"') \
            .add_query_string('unique', 'prints') \
            .add_query_string('order', 'released') \
            .add_query_string('format', 'json')

        return self.client.execute_request(self.request.build(), rate_limit_delay=rate_limit_delay)
