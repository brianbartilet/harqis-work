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

