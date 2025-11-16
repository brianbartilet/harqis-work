from apps.echo_mtg.references.web.base_api_service_fe import BaseApiServiceAppEchoMtgFe

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceEchoMTGCardItem(BaseApiServiceAppEchoMtgFe):

    def __init__(self, config, **kwargs):
        super(ApiServiceEchoMTGCardItem, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('item')

    @deserialized(dict)
    def get_card_meta(self, emid: str):
        self.request.get() \
            .add_query_string('emid', emid)

        return self.client.execute_request(self.request.build())
