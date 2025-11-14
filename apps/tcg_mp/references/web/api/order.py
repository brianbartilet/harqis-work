from typing import List, Any

from apps.tcg_mp.references.dto.order import DtoOrderSummaryByStatus
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

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

    @deserialized(List[DtoOrderSummaryByStatus], child='data', many=True)
    def get_orders(self, by_status: int = None):
        payload = {
            'date_range_from': None,
            'date_range_to': None,
            'is_buyer': "0",
            'item': None,
            'name': None,
            'order_id': None,
            'page': None,
            'sort_by': None,
            'status': by_status,
        }
        self.request.post() \
            .add_uri_parameter('filter') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict[Any, Any], child='data.data.0')
    def get_order_detail(self, order_id):
        self.request.get() \
            .add_uri_parameter(order_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict[Any, Any], child='data.data.0')
    def get_order_qr_code(self, order_id):
        self.request.get() \
            .add_uri_parameter('show_qr') \
            .add_uri_parameter(order_id)

        return self.client.execute_request(self.request.build())

