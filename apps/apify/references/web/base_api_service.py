"""
Base service for the Apify REST API v2.

API reference: https://docs.apify.com/api/v2
Base URL:      https://api.apify.com/v2/

Authentication is a Bearer token in the Authorization header. Tokens are
created on the Integrations page: https://console.apify.com/account#/integrations

Apify exposes a few orthogonal resource groups:
  - Actors        — pre-built / custom scrapers (run, list, sync-run)
  - Actor Runs    — execution status, logs
  - Datasets      — output collected from finished runs
  - Key-Value     — arbitrary key/value records produced by a run
  - Request Queue — for actors that crawl

The trends.py service layered on top picks well-known public actors
(Google Trends, Instagram, Facebook, TikTok, Reddit) and exposes them as
single-call helpers using the synchronous run-and-return-dataset endpoint.
"""
from urllib.parse import quote

from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders


class BaseApiServiceApify(BaseFixtureServiceRest):
    """Shared base for every Apify resource service."""

    def __init__(self, config, **kwargs):
        super(BaseApiServiceApify, self).__init__(config=config, **kwargs)
        self.api_key = kwargs.get('api_key', config.app_data['api_key'])
        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {self.api_key}')

    @staticmethod
    def encode_actor_id(actor_id: str) -> str:
        """
        Apify actor IDs use the form ``username/actor-name`` (canonical) or a
        hex hash. The REST API requires the slash to be replaced with ``~``
        so it survives the URL path. This helper is idempotent for hash IDs.
        """
        return quote(actor_id.replace('/', '~'), safe='~')
