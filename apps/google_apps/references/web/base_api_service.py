from apps.google_apps.references.web.client import GoogleApiClient

from core.web.services.fixtures.rest import BaseFixtureServiceRest

from typing import TypeVar
TWebService = TypeVar("TWebService")


class BaseApiServiceGoogle(BaseFixtureServiceRest):

    def __init__(self, config, use_gclient=True, **kwargs):
        self.client_discovery = None
        if use_gclient:
            self.client_discovery = GoogleApiClient(
                scopes_list=config.app_data.get("scopes"),
                credentials=config.app_data.get("credentials"),
                storage=config.app_data.get("storage"),
                service_account=config.app_data.get("service_account"),
                proxies=kwargs.get("proxies")
            )
        else:
            super(BaseApiServiceGoogle, self) .__init__(config, **kwargs)




