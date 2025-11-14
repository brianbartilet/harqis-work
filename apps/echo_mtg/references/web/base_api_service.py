from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders
from core.web.services.core.decorators.deserializer import deserialized


class BaseApiServiceAppEchoMtg(BaseFixtureServiceRest):
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
        super(BaseApiServiceAppEchoMtg, self).__init__(config=config, **kwargs)

        self.username = config.app_data.get('username', None)
        self.password = config.app_data.get('password', None)
        self.token = config.app_data.get('token', None)

        if not self.token:
            self.authenticate()

        self.request\
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {self.token}')\
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json')

    @deserialized(dict)
    def authenticate(self, username: str = None, password: str = None):
        self.request.post() \
            .add_uri_parameter('user') \
            .add_uri_parameter('auth')

        payload = {
            'email': username if username is not None else self.username,
            'password': password if password is not None else self.password
        }
        self.request.add_json_payload(payload)

        response = self.client.execute_request(self.request.build())
        self.token = response.data['token']

        return response

