from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders
from core.web.services.core.decorators.deserializer import deserialized


class BaseApiServiceAppTcgMp(BaseFixtureServiceRest):
    """
       Extends the BaseFixtureServiceRest to provide additional services tailored for the application.

       This class initializes the service application with specific configuration settings
       and any additional keyword arguments that might be necessary for the initialization of the base service.

       """
    def __init__(self, config, **kwargs):
        """
        Initialize the BaseServiceApp with configuration settings and other optional keyword arguments.

        Args:
            config: Configuration settings for the service application.
            **kwargs: Arbitrary keyword arguments that are passed to the parent class initializer.
        """
        super(BaseApiServiceAppTcgMp, self).__init__(config=config, **kwargs)
        self.username = config.app_data.get('username', None)
        self.password = config.app_data.get('password', None)
        self.user_id = config.app_data.get('user_id', None)
        self.token = config.app_data.get('token', None)

        if not self.token:
            self.authenticate()

        self.request\
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'{self.token}')

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





