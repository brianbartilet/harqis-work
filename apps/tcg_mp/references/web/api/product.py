from typing import List

from apps.tcg_mp.references.dto.search import DtoFilterResult
from apps.tcg_mp.references.dto.product import DtoCardData
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTcgMpProducts(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpProducts, self).__init__(config, **kwargs)
        self.category_id = config.app_data['category_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('product')\

    @deserialized(List[DtoFilterResult], child='data', many=True)
    def search_card(self, card_name: str, page: int = 1, items: int = 100):
        payload = {
            'category_id': self.category_id,
            'name': card_name,
            'page': page,
            'items': items
        }
        self.request.post()\
            .add_uri_parameter('filter')\
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(DtoCardData, child='data.data.0', many=False)
    def get_single_card(self, card_id: str):
        self.request.get()\
            .add_uri_parameter('single')\
            .add_uri_parameter(card_id)

        return self.client.execute_request(self.request.build())
