from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceJira(BaseFixtureServiceRest):
    """
    Base service for the Jira REST API v2.

    Supports both Jira Cloud (Basic Auth: email + API token) and
    Jira Data Center / Server (Bearer token: personal access token).

    The domain is read from config.app_data and injected into the base URL
    at runtime, overriding the placeholder set in apps_config.yaml.

    Auth method is determined by whether 'email' is present in app_data:
      - email present  → Basic Auth: base64(email:api_token)
      - email absent   → Bearer token: api_token used directly
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceJira, self).__init__(config=config, **kwargs)
        domain = kwargs.get('domain', config.app_data['domain'])
        api_token = kwargs.get('api_token', config.app_data['api_token'])
        email = kwargs.get('email', config.app_data.get('email'))

        # Override placeholder base_url with the real domain
        self.client.base_url = f"https://{domain}/rest/api/2/"

        if email:
            import base64
            credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
            auth_header = f'Basic {credentials}'
        else:
            auth_header = f'Bearer {api_token}'

        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, auth_header)
