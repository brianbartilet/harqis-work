import os

from typing import List, Any

from apps.tcg_mp.references.dto.order import DtoOrderSummaryByStatus, EnumTcgOrderStatus
from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.decorators.deserializer import deserialized
from core.utilities.resources.download_file import ServiceDownloadFile


class ApiServiceTcgMpOrder(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpOrder, self).__init__(config, **kwargs)
        self.user_id = config.app_data['user_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('order')

    @deserialized(List[DtoOrderSummaryByStatus], child='data', many=True)
    def get_orders(self, by_status: EnumTcgOrderStatus = EnumTcgOrderStatus.PENDING_DROP_OFF, **kwargs):
        payload = {
            'date_range_from': kwargs.get('date_range_from', None),
            'date_range_to': kwargs.get('date_range_to', None),
            'is_buyer': kwargs.get('is_buyer', "0"),
            'item': kwargs.get('item', ''),
            'name': kwargs.get('name', ''),
            'order_id': kwargs.get('order_id', ''),
            'page': kwargs.get('page', ''),
            'sort_by': kwargs.get('sort_by', ''),
            'status': by_status.value[0],
        }
        self.request.post() \
            .add_uri_parameter('filter') \
            .add_json_payload(payload)

        response = self.client.execute_request(self.request.build())
        return response

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

    def download_order_qr(self, order_id, path=None):
        """Download an order's QR code image to disk.

        Resolves the QR image URL via ``get_order_qr_code`` then saves the image
        to ``path`` (defaults to the configured ``save_path``).

        Args:
            order_id: The order ID string.
            path: Destination folder. Defaults to ``config.app_data['save_path']``.

        Returns:
            A dict with ``order_id``, the source ``qr`` URL, and the local ``file_path``.
        """
        qr = self.get_order_qr_code(order_id)
        url = qr['qr'] if isinstance(qr, dict) else None
        if not url:
            raise Exception(f"No QR image URL found for order {order_id}")

        path = path or self.config.app_data['save_path']
        file_name = f"qr_{order_id}_{url.split('/')[-1]}"

        downloader = ServiceDownloadFile(url=url)
        downloader.download_file(file_name, path)

        return {
            'order_id': order_id,
            'qr': url,
            'file_path': os.path.join(path, file_name),
        }

