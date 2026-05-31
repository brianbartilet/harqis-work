from core.web.services.core.decorators.deserializer import deserialized
from apps.spotify.references.web.base_api_service import BaseApiServiceSpotify
from apps.spotify.references.constants import TIME_RANGE_SHORT


class ApiServiceSpotifyPersonalization(BaseApiServiceSpotify):
    """The user's top tracks and top artists over a rolling time range.

    Provides the "identity / mood" layer for the HFL ingest: what defined
    the listening period regardless of the 50-track recently-played cap.
    Both return the raw Spotify JSON envelope (the list is under ``items``).
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceSpotifyPersonalization, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_top_tracks(self, time_range: str = TIME_RANGE_SHORT,
                       limit: int = 20) -> dict:
        """Return the user's top tracks.

        Args:
            time_range: short_term (~4 wks) / medium_term (~6 mo) / long_term.
            limit: Max items to return (1-50).
        """
        self.request.get() \
            .add_uri_parameter('me') \
            .add_uri_parameter('top') \
            .add_uri_parameter('tracks') \
            .add_query_string('time_range', time_range) \
            .add_query_string('limit', max(1, min(int(limit), 50)))

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_top_artists(self, time_range: str = TIME_RANGE_SHORT,
                        limit: int = 20) -> dict:
        """Return the user's top artists.

        Args:
            time_range: short_term (~4 wks) / medium_term (~6 mo) / long_term.
            limit: Max items to return (1-50).
        """
        self.request.get() \
            .add_uri_parameter('me') \
            .add_uri_parameter('top') \
            .add_uri_parameter('artists') \
            .add_query_string('time_range', time_range) \
            .add_query_string('limit', max(1, min(int(limit), 50)))

        return self.client.execute_request(self.request.build())
