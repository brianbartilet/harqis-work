from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp
from apps.tcg_mp.references.dto.listing import ListingStatus

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTcgMpMerchant(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpMerchant, self).__init__(config, **kwargs)
        self.user_id = config.app_data['user_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('merchant')

    @deserialized(dict, child='data.data')
    def set_listing_status(self, status: ListingStatus):
        self.request.get() \
            .add_uri_parameter('set-listing-status') \
            .add_uri_parameter(int(status))

        return self.client.execute_request(self.request.build())

