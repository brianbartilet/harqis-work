from __future__ import annotations

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from apps.google_apps.references.web.client import GoogleApiClient


class BaseApiServiceYouTube:
    """Build an authorized Google discovery client for a YouTube API."""

    SERVICE_NAME = ""
    SERVICE_VERSION = ""

    def __init__(self, config, **kwargs) -> None:
        if not self.SERVICE_NAME or not self.SERVICE_VERSION:
            raise ValueError("YouTube service name and version must be configured")

        self.config = config
        self.client_discovery = GoogleApiClient(
            scopes_list=config.app_data.get("scopes", []),
            credentials=config.app_data.get("credentials"),
            storage=config.app_data.get("storage"),
            proxies=kwargs.get("proxies"),
        )
        credentials = self.client_discovery.authorize()
        authorized_http = AuthorizedHttp(credentials, http=httplib2.Http())
        self.service = build(
            self.SERVICE_NAME,
            self.SERVICE_VERSION,
            http=authorized_http,
            cache_discovery=False,
        )
