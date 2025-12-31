from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTcgMpUserViewCart(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpUserViewCart, self).__init__(config, **kwargs)
        self.user_id = config.app_data['user_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('cart')

    @deserialized(dict, child='data.data.0', many=True)
    def get_account_summary(self):
        self.request.get() \
            .add_uri_parameter('summary')
        return self.client.execute_request(self.request.build())

