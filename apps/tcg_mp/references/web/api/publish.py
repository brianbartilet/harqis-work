from typing import List

from apps.tcg_mp.references.dto.search import DtoFilterResult
from apps.tcg_mp.references.dto.product import DtoCardData
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.decorators.deserializer import deserialized
from core.web.services.core.constants.payload_type import PayloadType
from core.web.services.core.constants.http_headers import HttpHeaders

class ApiServiceTcgMpPublish(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpPublish, self).__init__(config, **kwargs)
        self.category_id = config.app_data['category_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('publish')\

        self.request.clear_headers()
        self.request.add_header(HttpHeaders.AUTHORIZATION, f'{self.token}')

    @deserialized(dict, child='data.data')
    def add_listing(self, product_id: int, price: float, quantity=1, foil=0, language="EN", condition="NM", signed=0):
        data = {
            'price': price,
            'quantity': quantity,
            'language': language,
            'condition': condition,
            'foil': foil,
            'signed': signed,
            'product_id': product_id,
        }

        self.request.post()\
            .add_uri_parameter('add')\
            .add_payload(data, PayloadType.DICT)

        return self.client.execute_request(self.request.build())

    def edit_listing(self, listing_id: int, price: float, quantity=1, foil=0, language="EN", condition="NM", signed=0):
        data = {
            'price': price,
            'quantity': quantity,
            'language': language,
            'condition': condition,
            'foil': foil,
            'signed': signed,
            'id': listing_id,
        }

        self.request.post()\
            .add_uri_parameter('edit')\
            .add_payload(data, PayloadType.DICT)

        return self.client.execute_request(self.request.build())

