from apps.echo_mtg.references.dto.inventory import DtoPortfolioStats
from apps.echo_mtg.references.dto.card import DtoEchoMTGCard
from apps.echo_mtg.references.web.base_api_service import BaseApiServiceAppEchoMtg

from core.web.services.core.decorators.deserializer import deserialized
from core.web.services.core.constants.http_headers import HttpHeaders

from typing import List

class ApiServiceEchoMTGInventory(BaseApiServiceAppEchoMtg):

    def __init__(self, config, **kwargs):
        super(ApiServiceEchoMTGInventory, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('inventory')

    @deserialized(DtoPortfolioStats, child='stats')
    def get_quick_stats(self):
        self.request.get() \
            .add_uri_parameter('quickstats')
        return self.client.execute_request(self.request.build())

    @deserialized(List[dict], child='items')
    def get_collection(self, start=0, limit=10000, sort="i.id", direction="DESC", tradable_only=0):
        self.request.get() \
            .add_uri_parameter('view')\
            .add_query_string('start', start)\
            .add_query_string('limit', limit)\
            .add_query_string('sort', sort)\
            .add_query_string('direction', direction)\
            .add_query_string('tradable', tradable_only)

        return self.client.execute_request(self.request.build())

    def get_all_collection(self, tradable_only=0, *, max_items=100_000):
        """Read one inventory partition completely; keep get_collection paged.

        EchoMTG caps each response at 1,000 items. Advance by the actual
        response length and read until an empty page, not a short page.
        Invalid/repeated pages and the safety bound raise rather than return
        partial inventory to callers that may remove cards or edit listings.
        """
        items = []
        seen_ids = set()
        while True:
            page = self.get_collection(
                start=len(items), limit=1000, sort="i.id", direction="ASC",
                tradable_only=tradable_only,
            )
            if not isinstance(page, list):
                raise ValueError("EchoMTG collection page must be a list")
            if not page:
                return items
            for item in page:
                if not isinstance(item, dict) or not str(item.get("inventory_id") or "").strip():
                    raise ValueError("EchoMTG collection item is missing inventory_id")
                inventory_id = str(item["inventory_id"]).strip()
                if inventory_id in seen_ids:
                    raise ValueError(f"EchoMTG collection repeated inventory_id {inventory_id}")
                seen_ids.add(inventory_id)
            if len(items) + len(page) > max_items:
                raise ValueError(f"EchoMTG collection exceeded max_items={max_items}")
            items.extend(page)

    @deserialized(List[dict], child='results')
    def search_card(self, emid, tradable_only=1):
        self.request.get() \
            .add_uri_parameter('search')\
            .add_query_string('emid', emid)\
            .add_query_string('tradable', tradable_only)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def remove_item(self, inventory_id):
        """Remove (delete) an item from the inventory.

        Args:
            inventory_id: The inventory record ID to delete.
        """
        payload = {
            'id': inventory_id,
        }

        self.request.post() \
            .add_uri_parameter('remove') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

