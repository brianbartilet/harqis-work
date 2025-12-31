from apps.ynab.references.web.base_api_service import BaseApiServiceYouNeedABudget
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceYNABUser(BaseApiServiceYouNeedABudget):

    def __init__(self, config, **kwargs):
        super(ApiServiceYNABUser, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('user')

    @deserialized(dict)
    def get_user_info(self):
        self.request.get()

        return self.client.execute_request(self.request.build())


