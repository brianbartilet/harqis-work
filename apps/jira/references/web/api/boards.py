"""
Jira Agile API — board endpoints (`/rest/agile/1.0/board/...`).

The base service in `base_api_service.py` pins `base_url` to `/rest/api/2/`,
which is fine for issue / project / user endpoints but doesn't expose Agile
board operations. This module overrides the base URL to the agile namespace
and adds a single `get_board_issues_by_status` helper used by the
`workflows/hud/tasks/hud_jira.show_jira_board` widget.

The `board_id` parameter is the same numeric value that appears as
`rapidView=<id>` in the URL of a Jira Software board, e.g.
`https://jira.sehlat.io/secure/RapidBoard.jspa?rapidView=1790` → `board_id=1790`.
"""

from typing import List, Optional

from apps.jira.references.web.base_api_service import BaseApiServiceJira

from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceJiraBoards(BaseApiServiceJira):
    """Read-only operations against Jira Software boards."""

    def __init__(self, config, **kwargs):
        super(ApiServiceJiraBoards, self).__init__(config, **kwargs)
        # Re-point the client at the agile namespace. The parent set `/rest/api/2/`.
        domain = kwargs.get('domain', config.app_data['domain'])
        self.client.base_url = f"https://{domain}/rest/agile/1.0/"

    @deserialized(dict)
    def get_configuration(self, board_id: int):
        """Return the board's metadata including the column → status mapping.

        The response shape (Jira Agile API):
            {
              "id": <board_id>,
              "name": "...",
              "type": "scrum" | "kanban",
              "columnConfig": {
                "columns": [
                  {"name": "In Review", "statuses": [{"id": "10001"}, ...]},
                  ...
                ]
              },
              "estimation": {...},
              "ranking": {...}
            }

        The `columns[i].statuses[j].id` values are the canonical underlying
        status IDs each board column maps to. The HUD widget uses this to
        bucket issues by *column membership* — necessary because a column
        named "In Review" can map to underlying statuses called "Code Review",
        "QA Review", etc., that direct status-name matching would miss.
        """
        self.request.get() \
            .add_uri_parameter('board') \
            .add_uri_parameter(str(board_id)) \
            .add_uri_parameter('configuration')

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_board_issues(
        self,
        board_id: int,
        jql: Optional[str] = None,
        fields: Optional[List[str]] = None,
        max_results: int = 50,
        start_at: int = 0,
    ):
        """Return issues on a Jira Software board, optionally filtered by JQL.

        Use this for the "current sprint focus view" pattern — fetch every
        sprint-scoped issue in one call, then group client-side by
        `fields.status.name`. A single broad call is cheaper than N per-status
        calls and produces accurate grouping even when status display names
        don't exactly match the column headers on the board.

        Args:
            board_id:    Numeric board id (the `rapidView` value in the board URL).
            jql:         Optional JQL filter, e.g. `'sprint in openSprints()'`.
            fields:      Specific issue fields to return (request only what you
                         render — smaller payload, faster response).
            max_results: Page size cap. Bump above 50 when scanning a whole
                         sprint that may contain >50 tickets.
            start_at:    Pagination offset.

        Returns:
            Dict with the standard Jira search-result shape:
              {"issues": [...], "total": N, "startAt": ..., "maxResults": ...}
        """
        self.request.get() \
            .add_uri_parameter('board') \
            .add_uri_parameter(str(board_id)) \
            .add_uri_parameter('issue') \
            .add_query_string('maxResults', max_results) \
            .add_query_string('startAt', start_at)

        if jql:
            self.request.add_query_string('jql', jql)
        if fields:
            self.request.add_query_string('fields', ','.join(fields))

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_board_issues_by_status(
        self,
        board_id: int,
        status: str,
        fields: Optional[List[str]] = None,
        max_results: int = 50,
        start_at: int = 0,
    ):
        """Return issues on a Jira Software board filtered to a single status.

        Args:
            board_id:    Numeric board id (the `rapidView` value in the board URL).
            status:      Status name as it appears on the board column header
                         (e.g. "In Review", "In Progress", "Ready", "In Analysis").
            fields:      Specific issue fields to return. None pulls the
                         platform default. Most HUD callers want
                         ['summary','assignee','priority','fixVersions','issuetype'].
            max_results: Page size cap (Jira default is 50).
            start_at:    Pagination offset.

        Returns:
            Dict with the standard Jira search-result shape:
              {"issues": [...], "total": N, "startAt": ..., "maxResults": ...}
        """
        # Use double-quotes around the status so multi-word names are accepted by JQL.
        jql = f'status = "{status}"'

        self.request.get() \
            .add_uri_parameter('board') \
            .add_uri_parameter(str(board_id)) \
            .add_uri_parameter('issue') \
            .add_query_string('jql', jql) \
            .add_query_string('maxResults', max_results) \
            .add_query_string('startAt', start_at)

        if fields:
            self.request.add_query_string('fields', ','.join(fields))

        return self.client.execute_request(self.request.build())
