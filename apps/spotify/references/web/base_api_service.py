import httpx

from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders
from core.utilities.logging.custom_logger import create_logger

from apps.spotify.references.constants import SPOTIFY_TOKEN_URL

_log = create_logger("spotify.base_api_service")


class BaseApiServiceSpotify(BaseFixtureServiceRest):
    """
    Base service for the Spotify Web API (https://api.spotify.com/v1/).

    Auth is OAuth2 Authorization Code with a refresh token. Spotify access
    tokens expire in ~1 hour, so — unlike a static bearer key — this service
    exchanges the long-lived ``refresh_token`` for a fresh access token on
    every construction (POST to accounts.spotify.com/api/token with
    ``grant_type=refresh_token`` and HTTP Basic client credentials), then
    sets it as the ``Authorization: Bearer`` header for every request.

    Credentials come from config.app_data (resolved from .env/apps.env):
        client_id, client_secret, refresh_token

    The one-time handshake that mints ``refresh_token`` (authorize with the
    user-read-recently-played + user-top-read scopes, exchange the code) is
    done out of band — see apps/spotify/README.md.

    A fresh service instance refreshes once; reuse the instance for several
    calls within the ~1h window rather than reconstructing per request.
    """

    def __init__(self, config, **kwargs):
        super(BaseApiServiceSpotify, self).__init__(config=config, **kwargs)
        self.client_id = kwargs.get('client_id', config.app_data['client_id'])
        self.client_secret = kwargs.get('client_secret', config.app_data['client_secret'])
        self.refresh_token = kwargs.get('refresh_token', config.app_data['refresh_token'])

        self.access_token = kwargs.get('access_token') or self._refresh_access_token()

        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_header(HttpHeaders.AUTHORIZATION, f'Bearer {self.access_token}')

    def _refresh_access_token(self) -> str:
        """Exchange the refresh token for a fresh access token.

        Raises on HTTP/JSON failure so the caller (an ingest task) can turn
        it into a clean skip rather than a half-built service.
        """
        resp = httpx.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            auth=(self.client_id, self.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        resp.raise_for_status()
        token = (resp.json() or {}).get("access_token")
        if not token:
            raise ValueError("Spotify token endpoint returned no access_token")
        _log.info("spotify: refreshed access token")
        return token
