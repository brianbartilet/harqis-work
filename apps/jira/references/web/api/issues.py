from typing import List, Optional

from apps.jira.references.web.base_api_service import BaseApiServiceJira
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceJiraIssues(BaseApiServiceJira):
    """
    Jira Cloud REST API v3 — issue operations.

    Methods:
        search_issues()     → Search issues via JQL
        get_issue()         → Single issue by key or ID
        create_issue()      → Create a new issue
        update_issue()      → Update fields on an existing issue
        get_issue_comments() → Comments on an issue
        add_comment()       → Add a comment to an issue
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceJiraIssues, self).__init__(config, **kwargs)

    @deserialized(dict)
    def search_issues(self, jql: str, max_results: int = 50, start_at: int = 0,
                      fields: Optional[List[str]] = None):
        """
        Search for issues using JQL (Jira Query Language).

        Args:
            jql:         JQL query string (e.g. 'project=HARQIS AND status=Open').
            max_results: Maximum results to return (default 50, max 100).
            start_at:    Pagination offset (default 0).
            fields:      Specific fields to return. None returns all fields.

        Returns:
            Dict with keys: issues (list), total, startAt, maxResults.
        """
        payload = {
            'jql': jql,
            'maxResults': max_results,
            'startAt': start_at,
        }
        if fields:
            payload['fields'] = fields

        self.request.post() \
            .add_uri_parameter('search') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_issue(self, issue_key: str, fields: Optional[List[str]] = None):
        """
        Get a single issue by its key or ID.

        Args:
            issue_key: Issue key (e.g. 'HARQIS-42') or numeric ID.
            fields:    Specific fields to return. None returns all fields.
        """
        self.request.get() \
            .add_uri_parameter('issue') \
            .add_uri_parameter(issue_key)

        if fields:
            self.request.add_query_string('fields', ','.join(fields))

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_issue(self, project_key: str, summary: str, issue_type: str = 'Task',
                     description: str = None, assignee_account_id: str = None,
                     labels: Optional[List[str]] = None, priority: str = None):
        """
        Create a new issue in a project.

        Args:
            project_key:          Project key (e.g. 'HARQIS').
            summary:              Issue summary/title (required).
            issue_type:           Issue type name (default 'Task').
            description:          Plain-text description.
            assignee_account_id:  Atlassian account ID of the assignee.
            labels:               List of label strings.
            priority:             Priority name (e.g. 'High', 'Medium', 'Low').
        """
        fields = {
            'project': {'key': project_key},
            'summary': summary,
            'issuetype': {'name': issue_type},
        }
        if description:
            fields['description'] = description
        if assignee_account_id:
            fields['assignee'] = {'accountId': assignee_account_id}
        if labels:
            fields['labels'] = labels
        if priority:
            fields['priority'] = {'name': priority}

        self.request.post() \
            .add_uri_parameter('issue') \
            .add_json_payload({'fields': fields})

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_issue(self, issue_key: str, summary: str = None, description: str = None,
                     assignee_account_id: str = None, priority: str = None,
                     labels: Optional[List[str]] = None):
        """
        Update fields on an existing issue.

        Args:
            issue_key:            Issue key (e.g. 'HARQIS-42').
            summary:              New summary.
            description:          New plain-text description.
            assignee_account_id:  Atlassian account ID of the new assignee.
            priority:             New priority name.
            labels:               New label list (replaces existing).
        """
        fields = {}
        if summary is not None:
            fields['summary'] = summary
        if description is not None:
            fields['description'] = description
        if assignee_account_id is not None:
            fields['assignee'] = {'accountId': assignee_account_id}
        if priority is not None:
            fields['priority'] = {'name': priority}
        if labels is not None:
            fields['labels'] = labels

        self.request.put() \
            .add_uri_parameter('issue') \
            .add_uri_parameter(issue_key) \
            .add_json_payload({'fields': fields})

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_issue_comments(self, issue_key: str, max_results: int = 50, start_at: int = 0):
        """
        Get comments on an issue.

        Args:
            issue_key:   Issue key (e.g. 'HARQIS-42').
            max_results: Maximum comments to return (default 50).
            start_at:    Pagination offset (default 0).
        """
        self.request.get() \
            .add_uri_parameter('issue') \
            .add_uri_parameter(issue_key) \
            .add_uri_parameter('comment') \
            .add_query_string('maxResults', max_results) \
            .add_query_string('startAt', start_at)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def add_comment(self, issue_key: str, text: str):
        """
        Add a plain-text comment to an issue.

        Args:
            issue_key: Issue key (e.g. 'HARQIS-42').
            text:      Comment body text.
        """
        self.request.post() \
            .add_uri_parameter('issue') \
            .add_uri_parameter(issue_key) \
            .add_uri_parameter('comment') \
            .add_json_payload({'body': text})

        return self.client.execute_request(self.request.build())
