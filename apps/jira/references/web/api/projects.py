from typing import List

from apps.jira.references.web.base_api_service import BaseApiServiceJira
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceJiraProjects(BaseApiServiceJira):
    """
    Jira Cloud REST API v3 — project operations.

    Methods:
        get_projects()      → All projects accessible to the authenticated user
        get_project()       → Single project by key or ID
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceJiraProjects, self).__init__(config, **kwargs)

    @deserialized(List[dict])
    def get_projects(self, max_results: int = 50, start_at: int = 0):
        """
        Return all projects visible to the authenticated user.

        Args:
            max_results: Maximum number of results (default 50).
            start_at:    Pagination offset (default 0).
        """
        self.request.get() \
            .add_uri_parameter('project') \
            .add_query_string('maxResults', max_results) \
            .add_query_string('startAt', start_at)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_project(self, project_key: str):
        """
        Get a single project by its key or numeric ID.

        Args:
            project_key: Project key (e.g. 'HARQIS') or numeric ID.
        """
        self.request.get() \
            .add_uri_parameter('project') \
            .add_uri_parameter(project_key)

        return self.client.execute_request(self.request.build())
