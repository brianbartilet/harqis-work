from work.apps.echo_mtg.references.dto.inventory import DtoPortfolioStats
from work.apps.echo_mtg.references.web.base_api_service import BaseApiServiceAppEchoMtg

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceEchoMTGInventory(BaseApiServiceAppEchoMtg):

    def __init__(self, config, **kwargs):
        super(ApiServiceEchoMTGInventory, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('inventory')

    @deserialized(DtoPortfolioStats, child='stats')
    def get_quick_stats(self):
        self.request.get()\
            .add_uri_parameter('quickstats')
        response = self.client.execute_request(self.request.build())
        return response
