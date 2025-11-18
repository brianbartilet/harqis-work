from apps.google_apps.references.web.client import GoogleApiClient

from core.web.services.fixtures.rest import BaseFixtureServiceRest

from typing import TypeVar
TWebService = TypeVar("TWebService")


class BaseApiServiceGoogle(BaseFixtureServiceRest):

    def __init__(self, config, use_gclient=True, scopes_list=None, **kwargs):
        if use_gclient:
            super(BaseApiServiceGoogle, self)\
                .__init__(config, client=GoogleApiClient, scopes_list=scopes_list, **kwargs)
        else:
            super(BaseApiServiceGoogle, self) .__init__(config, **kwargs)




