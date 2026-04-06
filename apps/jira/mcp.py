import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.jira.config import CONFIG
from apps.jira.references.web.api.projects import ApiServiceJiraProjects
from apps.jira.references.web.api.issues import ApiServiceJiraIssues
from apps.jira.references.web.api.users import ApiServiceJiraUsers

logger = logging.getLogger("harqis-mcp.jira")


def register_jira_tools(mcp: FastMCP):

    @mcp.tool()
    def get_jira_projects(max_results: int = 50) -> list[dict]:
        """Get all Jira projects accessible to the authenticated user.

        Args:
            max_results: Maximum number of projects to return (default 50).
        """
        logger.info("Tool called: get_jira_projects")
        result = ApiServiceJiraProjects(CONFIG).get_projects(max_results=max_results)
        result = result if isinstance(result, list) else []
        logger.info("get_jira_projects returned %d project(s)", len(result))
        return result

    @mcp.tool()
    def get_jira_project(project_key: str) -> dict:
        """Get details of a single Jira project.

        Args:
            project_key: Project key (e.g. 'HARQIS') or numeric ID.
        """
        logger.info("Tool called: get_jira_project project_key=%s", project_key)
        result = ApiServiceJiraProjects(CONFIG).get_project(project_key)
        result = result if isinstance(result, dict) else {}
        logger.info("get_jira_project name=%s", result.get("name"))
        return result

    @mcp.tool()
    def search_jira_issues(jql: str, max_results: int = 50, start_at: int = 0) -> dict:
        """Search Jira issues using JQL (Jira Query Language).

        Args:
            jql:         JQL query string (e.g. 'project=HARQIS AND status=Open').
            max_results: Maximum results to return (default 50, max 100).
            start_at:    Pagination offset (default 0).

        Returns:
            Dict with keys: issues (list), total, startAt, maxResults.
        """
        logger.info("Tool called: search_jira_issues jql=%s", jql)
        result = ApiServiceJiraIssues(CONFIG).search_issues(jql=jql, max_results=max_results, start_at=start_at)
        result = result if isinstance(result, dict) else {}
        logger.info("search_jira_issues total=%s", result.get("total"))
        return result

    @mcp.tool()
    def get_jira_issue(issue_key: str) -> dict:
        """Get details of a single Jira issue.

        Args:
            issue_key: Issue key (e.g. 'HARQIS-42') or numeric ID.
        """
        logger.info("Tool called: get_jira_issue issue_key=%s", issue_key)
        result = ApiServiceJiraIssues(CONFIG).get_issue(issue_key)
        result = result if isinstance(result, dict) else {}
        logger.info("get_jira_issue key=%s", result.get("key"))
        return result

    @mcp.tool()
    def create_jira_issue(project_key: str, summary: str, issue_type: str = 'Task',
                          description: str = None, priority: str = None) -> dict:
        """Create a new Jira issue.

        Args:
            project_key: Project key (e.g. 'HARQIS').
            summary:     Issue summary/title (required).
            issue_type:  Issue type (default 'Task'). Common: 'Bug', 'Story', 'Epic'.
            description: Optional plain-text description.
            priority:    Optional priority ('Highest', 'High', 'Medium', 'Low', 'Lowest').
        """
        logger.info("Tool called: create_jira_issue project=%s summary=%s", project_key, summary)
        result = ApiServiceJiraIssues(CONFIG).create_issue(
            project_key=project_key,
            summary=summary,
            issue_type=issue_type,
            description=description,
            priority=priority
        )
        result = result if isinstance(result, dict) else {}
        logger.info("create_jira_issue created key=%s", result.get("key"))
        return result

    @mcp.tool()
    def update_jira_issue(issue_key: str, summary: str = None, description: str = None,
                          priority: str = None) -> dict:
        """Update fields on an existing Jira issue.

        Args:
            issue_key:   Issue key (e.g. 'HARQIS-42').
            summary:     New summary.
            description: New plain-text description.
            priority:    New priority name.
        """
        logger.info("Tool called: update_jira_issue issue_key=%s", issue_key)
        result = ApiServiceJiraIssues(CONFIG).update_issue(
            issue_key=issue_key,
            summary=summary,
            description=description,
            priority=priority
        )
        result = result if isinstance(result, dict) else {}
        return result

    @mcp.tool()
    def get_jira_issue_comments(issue_key: str, max_results: int = 50) -> dict:
        """Get comments on a Jira issue.

        Args:
            issue_key:   Issue key (e.g. 'HARQIS-42').
            max_results: Maximum comments to return (default 50).
        """
        logger.info("Tool called: get_jira_issue_comments issue_key=%s", issue_key)
        result = ApiServiceJiraIssues(CONFIG).get_issue_comments(issue_key, max_results=max_results)
        result = result if isinstance(result, dict) else {}
        return result

    @mcp.tool()
    def add_jira_comment(issue_key: str, text: str) -> dict:
        """Add a comment to a Jira issue.

        Args:
            issue_key: Issue key (e.g. 'HARQIS-42').
            text:      Comment text.
        """
        logger.info("Tool called: add_jira_comment issue_key=%s", issue_key)
        result = ApiServiceJiraIssues(CONFIG).add_comment(issue_key, text)
        result = result if isinstance(result, dict) else {}
        logger.info("add_jira_comment comment_id=%s", result.get("id"))
        return result

    @mcp.tool()
    def get_jira_myself() -> dict:
        """Get the authenticated Jira user's profile."""
        logger.info("Tool called: get_jira_myself")
        result = ApiServiceJiraUsers(CONFIG).get_myself()
        result = result if isinstance(result, dict) else {}
        logger.info("get_jira_myself displayName=%s", result.get("displayName"))
        return result

    @mcp.tool()
    def search_jira_users(query: str, max_results: int = 50) -> list[dict]:
        """Search for Jira users by display name or email.

        Args:
            query:       Search string.
            max_results: Maximum results to return (default 50).
        """
        logger.info("Tool called: search_jira_users query=%s", query)
        result = ApiServiceJiraUsers(CONFIG).search_users(query=query, max_results=max_results)
        result = result if isinstance(result, list) else []
        logger.info("search_jira_users returned %d user(s)", len(result))
        return result
