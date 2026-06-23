from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceConfluence(BaseFixtureServiceRest):
    """
    Base service for the Confluence REST API.

    Supports both Confluence Cloud and Confluence Server / Data Center. The two
    differ in base path and auth, both resolved from config.app_data at runtime
    (overriding the placeholder base_url in apps_config.yaml):

      - Cloud  → host is `<domain>` (e.g. acme.atlassian.net), API lives under
                 `/wiki/rest/api/`, auth is Basic base64(email:api_token).
      - Server → host is `<domain>`, API lives under `/rest/api/`, auth is a
                 Bearer personal access token.

    Auth method, in order of precedence:
      1. `auth_mode` in app_data ('basic' | 'bearer') — explicit override.
      2. else inferred: email present → Cloud Basic auth; absent → Bearer.

    Server/DC personal access tokens are Bearer even when an account email is
    also configured, so set `auth_mode: 'bearer'` to force it regardless of email.

    `context_path` (default '/wiki') lets a Server/DC install that exposes the
    API at the root override the Cloud prefix — set it to '' in app_data.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceConfluence, self).__init__(config=config, **kwargs)
        domain = kwargs.get('domain', config.app_data['domain'])
        api_token = kwargs.get('api_token', config.app_data['api_token'])
        email = kwargs.get('email', config.app_data.get('email'))
        # Cloud serves the wiki API under /wiki; Server/DC often at the root.
        context_path = kwargs.get('context_path', config.app_data.get('context_path', '/wiki'))
        context_path = ('/' + context_path.strip('/')) if context_path.strip('/') else ''

        self.client.base_url = f"https://{domain}{context_path}/rest/api/"

        auth_mode = kwargs.get('auth_mode', config.app_data.get('auth_mode', '') or '')
        auth_mode = auth_mode.strip().lower() or ('basic' if email else 'bearer')

        if auth_mode == 'basic':
            import base64
            credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
            auth_header = f'Basic {credentials}'
        else:
            auth_header = f'Bearer {api_token}'

        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, auth_header)
