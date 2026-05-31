from typing import Optional

from core.web.services.core.decorators.deserializer import deserialized
from apps.spotify.references.web.base_api_service import BaseApiServiceSpotify
from apps.spotify.references.constants import RECENTLY_PLAYED_MAX_LIMIT


class ApiServiceSpotifyPlayer(BaseApiServiceSpotify):
    """Player-state endpoints: recently-played history + currently-playing.

    Both return the raw Spotify JSON envelope (a dict). The recently-played
    payload carries the play list under ``items`` plus paging ``cursors``;
    callers pull what they need rather than mapping the deep nested shape.
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceSpotifyPlayer, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_recently_played(self, limit: int = RECENTLY_PLAYED_MAX_LIMIT,
                            after_ms: Optional[int] = None) -> dict:
        """Return recently-played tracks (newest first), capped at 50.

        Args:
            limit: Max items to return (1-50). Spotify hard-caps this at 50.
            after_ms: Optional Unix-ms cursor — return only plays strictly
                after this instant. Omit for the latest page.
        """
        limit = max(1, min(int(limit), RECENTLY_PLAYED_MAX_LIMIT))
        self.request.get() \
            .add_uri_parameter('me') \
            .add_uri_parameter('player') \
            .add_uri_parameter('recently-played') \
            .add_query_string('limit', limit)
        if after_ms is not None:
            self.request.add_query_string('after', int(after_ms))

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_currently_playing(self) -> dict:
        """Return the track currently playing, or an empty dict if nothing is.

        Spotify replies 204 No Content when nothing is playing; that surfaces
        as an empty payload here.
        """
        self.request.get() \
            .add_uri_parameter('me') \
            .add_uri_parameter('player') \
            .add_uri_parameter('currently-playing')

        return self.client.execute_request(self.request.build())
