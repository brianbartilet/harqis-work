import base64
import requests as _requests

from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"


class BaseApiServiceReddit(BaseFixtureServiceRest):
    """
    Base service for the Reddit OAuth2 REST API.

    Auth:     OAuth2 password grant (script app type). Token fetched at init.
    Base URL: https://oauth.reddit.com  (all authenticated calls)
    Token:    https://www.reddit.com/api/v1/access_token  (exchange only)

    GET endpoints use the harqis-core request builder as normal.
    POST endpoints (form-encoded) use _post_form() which hits the API directly,
    because Reddit's write API requires application/x-www-form-urlencoded bodies,
    not JSON.

    Config app_data keys:
        client_id      — OAuth2 app client ID
        client_secret  — OAuth2 app client secret
        username       — Reddit account username
        password       — Reddit account password
        user_agent     — User-Agent string: "platform:app_id:version (by /u/user)"
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceReddit, self).__init__(config=config, **kwargs)

        client_id = kwargs.get('client_id', config.app_data.get('client_id', ''))
        client_secret = kwargs.get('client_secret', config.app_data.get('client_secret', ''))
        username = kwargs.get('username', config.app_data.get('username', ''))
        password = kwargs.get('password', config.app_data.get('password', ''))
        user_agent = kwargs.get('user_agent', config.app_data.get(
            'user_agent', 'python:harqis-work:v1.0.0 (by /u/harqis)'))

        self._user_agent = user_agent
        self._access_token = self._fetch_token(client_id, client_secret, username, password)

        # Set headers for harqis-core GET requests
        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'bearer {self._access_token}') \
            .add_header('User-Agent', user_agent)

        # Session for direct form-encoded POST requests
        self._session = _requests.Session()
        self._session.headers.update({
            'Authorization': f'bearer {self._access_token}',
            'User-Agent': user_agent,
        })

    @staticmethod
    def _fetch_token(client_id: str, client_secret: str,
                     username: str, password: str) -> str:
        """Exchange credentials for an OAuth2 access token."""
        if not client_id:
            return ''
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            'Authorization': f'Basic {credentials}',
            'User-Agent': 'python:harqis-work:v1.0.0 (by /u/harqis)',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        data = {'grant_type': 'password', 'username': username, 'password': password}
        r = _requests.post(TOKEN_URL, headers=headers, data=data, timeout=15)
        return r.json().get('access_token', '')

    def _post_form(self, path: str, data: dict) -> dict:
        """POST with application/x-www-form-urlencoded body (required for Reddit write API)."""
        r = self._session.post(f"{API_BASE}{path}", data=data, timeout=30)
        try:
            return r.json()
        except Exception:
            return {'status': r.status_code}
