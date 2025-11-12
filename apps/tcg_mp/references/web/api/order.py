from typing import List

from apps.tcg_mp.references.dto.order import DtoOrderSummary
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp
from apps.tcg_mp.references.web.api.auth import ApiServiceTcgMpAuth

from core.web.services.core.decorators.deserializer import deserialized
from core.web.services.core.constants.http_headers import HttpHeaders


class ApiServiceTcgMpOrder(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpOrder, self).__init__(config, **kwargs)
        self.user_id = config.app_data['user_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('order')

        auth = ApiServiceTcgMpAuth(self.config)
        auth.authenticate()
        self.request.add_header(HttpHeaders.AUTHORIZATION, auth.token)

    @deserialized(List[DtoOrderSummary], child='data.data.0', many=True)
    def get_orders(self):
        payload = {
            'date_range_from': None,
            'date_range_to': None,
            'is_buyer': "0",
            'item': None,
            'name': None,
            'order_id': None,
            'page': None,
            'sort_by': None,
            'status': None,
        }
        self.request.post() \
            .add_uri_parameter('filter') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())
