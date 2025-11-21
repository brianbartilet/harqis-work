import os
from urllib.parse import urlparse

from httplib2 import Http, ProxyInfo, socks
from core.config.env_variables import ENV_APP_SECRETS, ENV_ENABLE_PROXY

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials


class GoogleApiClient():
    def __init__(
        self,
        scopes_list,
        credentials: str | None = None,
        storage: str | None = None,
        **kwargs,
    ):

        self.scopes = list(scopes_list)
        self.credentials = (
            credentials or os.path.join(ENV_APP_SECRETS, "credentials.json")
        )
        self.storage = (
            storage or os.path.join(ENV_APP_SECRETS, "storage.json")
        )

        self._proxies = kwargs.get("proxies") or {}
        self._http = self._build_http()

    def _build_http(self) -> Http:
        """Create an Http client, optionally with proxy support."""
        if str(ENV_ENABLE_PROXY).lower() == "true":
            proxy_url = self._proxies.get("http") or self._proxies.get("https")
            if proxy_url:
                parsed = urlparse(proxy_url)
                proxy_info = ProxyInfo(
                    socks.PROXY_TYPE_HTTP,
                    parsed.hostname,
                    parsed.port or 8080,
                )
                return Http(proxy_info=proxy_info)
        # no proxy
        return Http()

    def authorize(self):
        creds = None

        # Load existing token
        if os.path.exists(self.storage):
            creds = Credentials.from_authorized_user_file(self.storage, self.scopes)

        # Refresh or re-auth if needed
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # The SAFE alternative — does NOT parse pytest args
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials,
                    self.scopes,
                )
                creds = flow.run_local_server(port=0)

            # save token
            with open(self.storage, 'w') as token:
                token.write(creds.to_json())

        return creds
