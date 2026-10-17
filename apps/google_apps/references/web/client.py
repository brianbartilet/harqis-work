import json
import os
from urllib.parse import urlparse

from httplib2 import Http, ProxyInfo, socks
from core.config.env_variables import ENV_APP_SECRETS, ENV_ENABLE_PROXY

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.exceptions import RefreshError


def _interactive_auth_allowed() -> bool:
    return os.environ.get("GOOGLE_ALLOW_INTERACTIVE_AUTH", "0") == "1" and not os.environ.get("PYTEST_CURRENT_TEST")


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
            os.path.join(ENV_APP_SECRETS, credentials)
            or os.path.join(ENV_APP_SECRETS, "credentials.json")
        )
        self.storage = (
            os.path.join(ENV_APP_SECRETS, storage)
            or os.path.join(ENV_APP_SECRETS, "storage.json")
        )

        # Optional service account: raw JSON key content, or a key file path (absolute or
        # relative to the secrets folder). Unset values come through as the literal '${VAR}'.
        account = str(kwargs.get("service_account") or "").strip()
        self.service_account = "" if account.startswith("${") else account

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

    def _service_account_credentials(self):
        account = self.service_account
        if account.startswith("{"):
            info = json.loads(account)
        else:
            path = account if os.path.isabs(account) else os.path.join(ENV_APP_SECRETS, account)
            with open(path, encoding="utf-8") as f:
                info = json.load(f)
        return service_account.Credentials.from_service_account_info(info, scopes=self.scopes)

    def authorize(self):
        # A service account needs no browser consent and its access does not expire, so it
        # suits unattended jobs; it only reaches what is shared with its email address.
        if self.service_account:
            return self._service_account_credentials()

        creds = None

        # Load existing token
        if os.path.exists(self.storage):
            creds = Credentials.from_authorized_user_file(self.storage, self.scopes)

        # Refresh or re-auth if needed
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError:
                    if not _interactive_auth_allowed():
                        raise
                    print("Rerunning auth flow...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials,
                        self.scopes,
                    )
                    creds = flow.run_local_server(port=0)
            else:
                if not _interactive_auth_allowed():
                    raise RuntimeError(
                        "Google OAuth credentials are missing or invalid; set "
                        "GOOGLE_ALLOW_INTERACTIVE_AUTH=1 outside pytest to refresh them."
                    )
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

    def remove_storage(self):
        if os.path.exists(self.storage):
            os.remove(self.storage)