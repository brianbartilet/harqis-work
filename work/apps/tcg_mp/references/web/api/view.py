from typing import List

from work.apps.tcg_mp.references.dto.listing import DtoListingItem
from work.apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTcgMpUser(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpUser, self).__init__(config, **kwargs)
        self.user_id = config.app_data['user_id']
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('view')

    @deserialized(List[DtoListingItem], child='data.data.0', many=True)
    def get_listings(self):
        self.request.get() \
            .add_uri_parameter('user') \
            .add_uri_parameter('listing') \
            .add_uri_parameter('user_id', str(self.user_id))

        return self.client.execute_request(self.request.build())
