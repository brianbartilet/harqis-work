"""
Actor Runs — list and inspect executions across the user's account.

Reference: https://docs.apify.com/api/v2#tag/Actor-runs
"""
from typing import Optional

from apps.apify.references.web.base_api_service import BaseApiServiceApify
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceApifyRuns(BaseApiServiceApify):
    """
    Account-wide actor run inspection.

    Methods:
        list_runs()    → Recent runs across all actors
        get_run()      → A single run's status and metadata
        get_run_log()  → The run's stdout/stderr log as plain text
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceApifyRuns, self).__init__(config, **kwargs)

    @deserialized(dict)
    def list_runs(self, status: Optional[str] = None, limit: Optional[int] = None,
                  offset: Optional[int] = None, desc: bool = True) -> dict:
        """
        List runs across the whole account (newest first by default).

        Args:
            status:  Filter by status — e.g. 'SUCCEEDED', 'FAILED', 'RUNNING'.
            limit:   Max runs to return.
            offset:  Pagination offset.
            desc:    Newest first if True (default).
        """
        self.request.get().add_uri_parameter('actor-runs')
        if status:
            self.request.add_query_string('status', status)
        if limit is not None:
            self.request.add_query_string('limit', limit)
        if offset is not None:
            self.request.add_query_string('offset', offset)
        if desc:
            self.request.add_query_string('desc', 'true')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_run(self, run_id: str) -> dict:
        """Fetch a run by ID. Includes status, dataset/store IDs, and stats."""
        self.request.get().add_uri_parameter(f'actor-runs/{run_id}')
        return self.client.execute_request(self.request.build())

    @deserialized(str)
    def get_run_log(self, run_id: str) -> str:
        """
        Stream the run's combined stdout/stderr log.

        Returned as plain text — pass through ``str()`` if the framework's
        deserializer wraps it.
        """
        self.request.get().add_uri_parameter(f'actor-runs/{run_id}/log')
        return self.client.execute_request(self.request.build())
