"""
Actors — list, retrieve, run.

Reference: https://docs.apify.com/api/v2#tag/Actors
"""
from typing import Optional, Dict, Any

from apps.apify.references.web.base_api_service import BaseApiServiceApify
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceApifyActors(BaseApiServiceApify):
    """
    Manage Apify actors (the unit of execution on the platform).

    Methods:
        list_actors()             → All actors visible to the token's user
        get_actor()               → Metadata for a single actor
        run_actor()               → Start an asynchronous run, returns run object
        run_actor_sync()          → Start a synchronous run, returns dataset items directly
        run_actor_sync_get_run()  → Synchronous run, returns the run object (for non-dataset output)
        abort_run()               → Abort a still-running execution
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceApifyActors, self).__init__(config, **kwargs)

    @deserialized(dict)
    def list_actors(self, my: bool = False, limit: Optional[int] = None,
                    offset: Optional[int] = None) -> dict:
        """
        List actors visible to the API token.

        Args:
            my:     If True, only actors owned by the token user.
            limit:  Max items to return.
            offset: Pagination offset.
        """
        self.request.get().add_uri_parameter('acts')
        if my:
            self.request.add_query_string('my', 'true')
        if limit is not None:
            self.request.add_query_string('limit', limit)
        if offset is not None:
            self.request.add_query_string('offset', offset)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_actor(self, actor_id: str) -> dict:
        """
        Get full metadata for one actor.

        Args:
            actor_id: ``username/actor-name`` (canonical) or hex ID.
        """
        encoded = self.encode_actor_id(actor_id)
        self.request.get().add_uri_parameter(f'acts/{encoded}')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def run_actor(self, actor_id: str, input_payload: Optional[Dict[str, Any]] = None,
                  build: Optional[str] = None, memory_mbytes: Optional[int] = None,
                  timeout_secs: Optional[int] = None, webhooks: Optional[str] = None) -> dict:
        """
        Start an asynchronous run. Returns the run object — the caller is
        responsible for polling status and fetching dataset items afterwards.

        Args:
            actor_id:       ``username/actor-name`` or hex ID.
            input_payload:  JSON body matching the actor's input schema.
            build:          Specific build tag/version (default 'latest').
            memory_mbytes:  Override memory allocation (must be a power of 2).
            timeout_secs:   Hard timeout for the run.
            webhooks:       Base64-encoded webhook spec — see Apify docs.
        """
        encoded = self.encode_actor_id(actor_id)
        self.request.post().add_uri_parameter(f'acts/{encoded}/runs')
        if build:
            self.request.add_query_string('build', build)
        if memory_mbytes is not None:
            self.request.add_query_string('memory', memory_mbytes)
        if timeout_secs is not None:
            self.request.add_query_string('timeout', timeout_secs)
        if webhooks:
            self.request.add_query_string('webhooks', webhooks)
        if input_payload is not None:
            self.request.add_json_payload(input_payload)
        return self.client.execute_request(self.request.build())

    @deserialized(list)
    def run_actor_sync(self, actor_id: str, input_payload: Optional[Dict[str, Any]] = None,
                       timeout_secs: Optional[int] = None, memory_mbytes: Optional[int] = None,
                       fmt: str = 'json', clean: bool = True,
                       limit: Optional[int] = None) -> Any:
        """
        Run an actor synchronously and return its default-dataset items.

        The endpoint blocks for up to 5 minutes (or ``timeout_secs``); for
        longer-running actors prefer ``run_actor()`` plus polling.

        Args:
            actor_id:      ``username/actor-name`` or hex ID.
            input_payload: JSON body matching the actor's input schema.
            timeout_secs:  Per-run timeout.
            memory_mbytes: Memory allocation.
            fmt:           'json' (default), 'jsonl', 'csv', 'xml', 'html', 'rss'.
            clean:         Drop hidden/empty fields. Default True.
            limit:         Max items to return.
        """
        encoded = self.encode_actor_id(actor_id)
        self.request.post().add_uri_parameter(f'acts/{encoded}/run-sync-get-dataset-items')
        self.request.add_query_string('format', fmt)
        if clean:
            self.request.add_query_string('clean', 'true')
        if timeout_secs is not None:
            self.request.add_query_string('timeout', timeout_secs)
        if memory_mbytes is not None:
            self.request.add_query_string('memory', memory_mbytes)
        if limit is not None:
            self.request.add_query_string('limit', limit)
        if input_payload is not None:
            self.request.add_json_payload(input_payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def run_actor_sync_get_run(self, actor_id: str,
                               input_payload: Optional[Dict[str, Any]] = None,
                               timeout_secs: Optional[int] = None,
                               memory_mbytes: Optional[int] = None) -> dict:
        """
        Synchronous variant that returns the run object instead of dataset items.

        Useful when the actor writes to a key-value store or request queue
        rather than (or in addition to) the default dataset.
        """
        encoded = self.encode_actor_id(actor_id)
        self.request.post().add_uri_parameter(f'acts/{encoded}/run-sync')
        if timeout_secs is not None:
            self.request.add_query_string('timeout', timeout_secs)
        if memory_mbytes is not None:
            self.request.add_query_string('memory', memory_mbytes)
        if input_payload is not None:
            self.request.add_json_payload(input_payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def abort_run(self, actor_id: str, run_id: str, gracefully: bool = False) -> dict:
        """Abort a still-running execution. ``gracefully=True`` requests a clean shutdown."""
        encoded = self.encode_actor_id(actor_id)
        self.request.post().add_uri_parameter(f'acts/{encoded}/runs/{run_id}/abort')
        if gracefully:
            self.request.add_query_string('gracefully', 'true')
        return self.client.execute_request(self.request.build())
