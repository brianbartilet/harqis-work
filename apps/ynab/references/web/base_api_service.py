from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceYouNeedABudget(BaseFixtureServiceRest):
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
        super(BaseApiServiceYouNeedABudget, self).__init__(config=config, **kwargs)
        self.access_token = kwargs.get('access_token', config.app_data['access_token'])

        self.request\
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {self.access_token}')