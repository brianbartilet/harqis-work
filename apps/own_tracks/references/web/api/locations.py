from typing import List, Optional

from apps.own_tracks.references.web.base_api_service import BaseApiServiceOwnTracks
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOwnTracksLocations(BaseApiServiceOwnTracks):
    """
    OwnTracks Recorder HTTP API — location queries.

    Methods:
        get_last()          → Last known location for all or specific devices
        get_history()       → Location history for a device within a time range
        list_devices()      → All known users/devices tracked by the Recorder
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceOwnTracksLocations, self).__init__(config, **kwargs)

    def get_last(self, user: str = None, device: str = None):
        """
        Get the last known location for all devices, or filter by user/device.

        Args:
            user:   Filter by username (e.g. 'brian'). Optional.
            device: Filter by device name (e.g. 'iphone'). Requires user.

        Returns:
            List of location dicts with: username, device, lat, lon, tst, acc, tid, topic.
        """
        self.request.get() \
            .add_uri_parameter('api') \
            .add_uri_parameter('0') \
            .add_uri_parameter('last')

        if user:
            self.request.add_query_string('user', user)
        if device:
            self.request.add_query_string('device', device)

        # Recorder returns a list of cards when devices have reported, but
        # degenerates to {} when empty — normalize so callers always see a list.
        response = self.client.execute_request(self.request.build())
        data = response.data if hasattr(response, 'data') else response
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
        return []

    @deserialized(dict)
    def get_history(self, user: str, device: str,
                    from_ts: Optional[int] = None, to_ts: Optional[int] = None):
        """
        Get location history for a specific user/device.

        Args:
            user:     Username (e.g. 'brian').
            device:   Device name (e.g. 'iphone').
            from_ts:  Start time as Unix timestamp. Optional.
            to_ts:    End time as Unix timestamp. Optional.

        Returns:
            Dict with key 'data' containing a list of location dicts.
        """
        self.request.get() \
            .add_uri_parameter('api') \
            .add_uri_parameter('0') \
            .add_uri_parameter('locations') \
            .add_query_string('user', user) \
            .add_query_string('device', device)

        if from_ts:
            self.request.add_query_string('from', from_ts)
        if to_ts:
            self.request.add_query_string('to', to_ts)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_devices(self):
        """
        List all users and devices known to the Recorder.

        Returns:
            Dict with key 'results' containing a list of {username, device, topic} dicts.
        """
        self.request.get() \
            .add_uri_parameter('api') \
            .add_uri_parameter('0') \
            .add_uri_parameter('list')

        return self.client.execute_request(self.request.build())
