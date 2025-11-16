from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceAppEchoMtgFe(BaseFixtureServiceRest):
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
        super(BaseApiServiceAppEchoMtgFe, self).__init__(config=config, **kwargs)

        self.username = config.app_data.get('username', None)
        self.password = config.app_data.get('password', None)
        self.token = config.app_data.get('token', None)


        self.request\
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json')
