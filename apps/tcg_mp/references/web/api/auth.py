from apps.tcg_mp.references.web.base_api_service import BaseApiServiceAppTcgMp
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTcgMpAuth(BaseApiServiceAppTcgMp):

    def __init__(self, config, **kwargs):
        super(ApiServiceTcgMpAuth, self).__init__(config, **kwargs)
        self.username = config.app_data['username']
        self.password = config.app_data['password']
        self.token = None
        self.user_id = None
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('auth')

    @deserialized(dict)
    def authenticate(self, username: str = None, password: str = None):
        self.request.add_uri_parameter('auth')
        payload = {
            'user': username if username is not None else self.username,
            'pwd': password if password is not None else self.password
        }
        self.request.post() \
            .add_json_payload(payload)

        response = self.client.execute_request(self.request.build())
        self.token = response.data['accessToken']
        self.user_id = response.data['id']

        return response
