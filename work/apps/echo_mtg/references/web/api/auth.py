from work.apps.echo_mtg.references.web.base_api_service import BaseApiServiceAppEchoMtg
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceEchoMTGAuth(BaseApiServiceAppEchoMtg):

    def __init__(self, config, **kwargs):
        super(ApiServiceEchoMTGAuth, self).__init__(config, **kwargs)
        self.username = config.app_data['username']
        self.password = config.app_data['password']

        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('user')

    @deserialized(dict)
    def authenticate(self, username: str = None, password: str = None):
        self.request.add_uri_parameter('auth')
        payload = {
            'email': username if username is not None else self.username,
            'password': password if password is not None else self.password
        }
        self.request.post() \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

