import os
from urllib.parse import urlparse

from httplib2 import Http, ProxyInfo, socks
from oauth2client import file, client, tools

from core.web.services.core.clients.rest import BaseWebClient
from core.config.env_variables import ENV_APP_CONFIG, ENV_ENABLE_PROXY


class GoogleApiClient(BaseWebClient):
    def __init__(
        self,
        scopes_list,
        credentials: str | None = None,
        storage: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.scopes = list(scopes_list)
        self.credentials = (
            credentials or os.path.join(ENV_APP_CONFIG, "credentials.json")
        )
        self.storage = (
            storage or os.path.join(ENV_APP_CONFIG, "storage.json")
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

    def authorize(self) -> Http:
        store = file.Storage(self.storage)
        creds = store.get()
        if not creds or creds.invalid:
            flow = client.flow_from_clientsecrets(self.credentials, self.scopes)
            creds = tools.run_flow(flow=flow, storage=store)

        return creds.authorize(self._http)
