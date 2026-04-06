from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceOwnTracks(BaseFixtureServiceRest):
    """
    Base service for the OwnTracks Recorder HTTP API.

    The Recorder runs locally (default: http://localhost:8083) and
    requires no authentication by default. If HTTP Basic Auth is
    enabled, credentials are read from config.app_data.

    Base URL: http://{host}:{port}/
    API prefix: api/0/
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceOwnTracks, self).__init__(config=config, **kwargs)

        # Override base_url with host/port from app_data (env-interpolated)
        host = kwargs.get('host', config.app_data.get('host', 'localhost'))
        port = kwargs.get('port', config.app_data.get('port', '8083'))
        self.client.base_url = f"http://{host}:{port}/"

        self.request.add_header(HttpHeaders.CONTENT_TYPE, 'application/json')

        # Optional Basic Auth — only applied if credentials are configured
        username = config.app_data.get('username')
        password = config.app_data.get('password')
        if username and password:
            import base64
            creds = base64.b64encode(f"{username}:{password}".encode()).decode()
            self.request.add_header(HttpHeaders.AUTHORIZATION, f'Basic {creds}')
