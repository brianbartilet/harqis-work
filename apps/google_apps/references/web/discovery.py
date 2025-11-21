from __future__ import annotations

import httplib2
from typing import Sequence
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp

from apps.google_apps.references.web.base_api_service import BaseApiServiceGoogle


class BaseGoogleDiscoveryService(BaseApiServiceGoogle):
    """
    Base class for Google APIs that use the discovery service.

    Responsibilities:
    - Take config + scopes
    - Use GoogleApiClient (via BaseApiServiceGoogle) to authorize
    - Build the discovery service (e.g. 'sheets', 'calendar', etc.)
    - Expose `self.service` for subclasses

    Subclasses must define:
        SERVICE_NAME (e.g. 'sheets', 'calendar')
        SERVICE_VERSION (e.g. 'v4', 'v3')
    """

    SERVICE_NAME: str = ""
    SERVICE_VERSION: str = "v3"

    def __init__(
        self,
        config,
        scopes_list: Sequence[str],
        **kwargs,
    ) -> None:
        if not self.SERVICE_NAME:
            raise ValueError("SERVICE_NAME must be set on subclasses of BaseGoogleDiscoveryService")

        super().__init__(config, use_gclient=True, scopes_list=scopes_list, **kwargs)

        # Authorize via GoogleApiClient and build the discovery service
        creds = self.client_discovery.authorize()
        authed_http = AuthorizedHttp(creds, http=httplib2.Http())

        # Optional: cache_discovery=False to avoid pickling cache in some environments
        self.service = build(
            self.SERVICE_NAME,
            self.SERVICE_VERSION,
            http=authed_http,
            cache_discovery=False,
        )
