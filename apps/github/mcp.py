"""GitHub MCP tools — repos, issues, PRs, commits, branches, and file content."""
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.github.config import CONFIG
from apps.github.references.web.api.repos import ApiServiceGitHubRepos

logger = logging.getLogger("harqis-mcp.github")


def register_github_tools(mcp: FastMCP):

    @mcp.tool()
    def github_get_me() -> dict:
        """Get the authenticated GitHub user profile."""
        logger.info("Tool called: github_get_me")
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.get_authenticated_user()
        logger.info("github_get_me login=%s", result.get("login"))
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def github_list_repos(visibility: str = "all", per_page: int = 30) -> list:
        """List repositories for the authenticated GitHub user.

        Args:
            visibility: Filter by visibility: 'all', 'public', or 'private' (default: all).
            per_page:   Number of repos to return (default: 30, max: 100).
        """
        logger.info("Tool called: github_list_repos visibility=%s", visibility)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.list_repos(visibility=visibility, per_page=per_page)
        result = result if isinstance(result, list) else []
        logger.info("github_list_repos returned %d repo(s)", len(result))
        return [r.__dict__ for r in result]

    @mcp.tool()
    def github_get_repo(owner: str, repo: str) -> dict:
        """Get details about a specific GitHub repository.

        Args:
            owner: Repository owner (username or org).
            repo:  Repository name.
        """
        logger.info("Tool called: github_get_repo %s/%s", owner, repo)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.get_repo(owner=owner, repo=repo)
        logger.info("github_get_repo name=%s", result.full_name)
        return result.__dict__

    @mcp.tool()
    def github_list_issues(owner: str, repo: str, state: str = "open", per_page: int = 30) -> list:
        """List issues for a GitHub repository.

        Args:
            owner:    Repository owner.
            repo:     Repository name.
            state:    Issue state: 'open', 'closed', or 'all' (default: open).
            per_page: Number of issues to return (default: 30).
        """
        logger.info("Tool called: github_list_issues %s/%s state=%s", owner, repo, state)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.list_issues(owner=owner, repo=repo, state=state, per_page=per_page)
        result = result if isinstance(result, list) else []
        logger.info("github_list_issues returned %d issue(s)", len(result))
        return [i.__dict__ for i in result]

    @mcp.tool()
    def github_get_issue(owner: str, repo: str, issue_number: int) -> dict:
        """Get a specific GitHub issue by number.

        Args:
            owner:        Repository owner.
            repo:         Repository name.
            issue_number: Issue number.
        """
        logger.info("Tool called: github_get_issue %s/%s #%d", owner, repo, issue_number)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.get_issue(owner=owner, repo=repo, issue_number=issue_number)
        logger.info("github_get_issue title=%s", result.title)
        return result.__dict__

    @mcp.tool()
    def github_create_issue(
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: Optional[list] = None,
    ) -> dict:
        """Create a new issue in a GitHub repository.

        Args:
            owner:  Repository owner.
            repo:   Repository name.
            title:  Issue title.
            body:   Issue description (Markdown).
            labels: List of label names to apply.
        """
        logger.info("Tool called: github_create_issue %s/%s title=%s", owner, repo, title)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.create_issue(owner=owner, repo=repo, title=title, body=body, labels=labels)
        logger.info("github_create_issue number=#%s", result.number)
        return result.__dict__

    @mcp.tool()
    def github_list_pull_requests(owner: str, repo: str, state: str = "open", per_page: int = 30) -> list:
        """List pull requests for a GitHub repository.

        Args:
            owner:    Repository owner.
            repo:     Repository name.
            state:    PR state: 'open', 'closed', or 'all' (default: open).
            per_page: Number of PRs to return (default: 30).
        """
        logger.info("Tool called: github_list_pull_requests %s/%s state=%s", owner, repo, state)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.list_pull_requests(owner=owner, repo=repo, state=state, per_page=per_page)
        result = result if isinstance(result, list) else []
        logger.info("github_list_pull_requests returned %d PR(s)", len(result))
        return [p.__dict__ for p in result]

    @mcp.tool()
    def github_get_pull_request(owner: str, repo: str, pr_number: int) -> dict:
        """Get a specific GitHub pull request by number.

        Args:
            owner:     Repository owner.
            repo:      Repository name.
            pr_number: Pull request number.
        """
        logger.info("Tool called: github_get_pull_request %s/%s #%d", owner, repo, pr_number)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.get_pull_request(owner=owner, repo=repo, pr_number=pr_number)
        logger.info("github_get_pull_request title=%s", result.title)
        return result.__dict__

    @mcp.tool()
    def github_list_commits(
        owner: str, repo: str, branch: Optional[str] = None, per_page: int = 30
    ) -> list:
        """List commits for a GitHub repository.

        Args:
            owner:    Repository owner.
            repo:     Repository name.
            branch:   Branch name or commit SHA to start from (default: default branch).
            per_page: Number of commits to return (default: 30).
        """
        logger.info("Tool called: github_list_commits %s/%s branch=%s", owner, repo, branch)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.list_commits(owner=owner, repo=repo, branch=branch, per_page=per_page)
        result = result if isinstance(result, list) else []
        logger.info("github_list_commits returned %d commit(s)", len(result))
        return [c.__dict__ for c in result]

    @mcp.tool()
    def github_list_branches(owner: str, repo: str) -> list:
        """List branches in a GitHub repository.

        Args:
            owner: Repository owner.
            repo:  Repository name.
        """
        logger.info("Tool called: github_list_branches %s/%s", owner, repo)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.list_branches(owner=owner, repo=repo)
        result = result if isinstance(result, list) else []
        logger.info("github_list_branches returned %d branch(es)", len(result))
        return [b.__dict__ for b in result]

    @mcp.tool()
    def github_get_file_content(
        owner: str, repo: str, path: str, ref: Optional[str] = None
    ) -> dict:
        """Get the decoded content of a file in a GitHub repository.

        Args:
            owner: Repository owner.
            repo:  Repository name.
            path:  File path relative to repository root (e.g. 'src/main.py').
            ref:   Branch, tag, or commit SHA (default: default branch).
        """
        logger.info("Tool called: github_get_file_content %s/%s path=%s ref=%s", owner, repo, path, ref)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.get_file_content(owner=owner, repo=repo, path=path, ref=ref)
        logger.info("github_get_file_content size=%s", result.get("size"))
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def github_search_repos(query: str, per_page: int = 20) -> list:
        """Search GitHub repositories by keyword.

        Args:
            query:    GitHub search query, e.g. 'language:python topic:fastapi'.
            per_page: Number of results to return (default: 20).
        """
        logger.info("Tool called: github_search_repos query=%s", query)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.search_repos(query=query, per_page=per_page)
        result = result if isinstance(result, list) else []
        logger.info("github_search_repos returned %d result(s)", len(result))
        return [r.__dict__ for r in result]

    @mcp.tool()
    def github_search_issues(query: str, per_page: int = 20) -> list:
        """Search GitHub issues and pull requests by keyword.

        Args:
            query:    GitHub search query, e.g. 'repo:owner/name is:open label:bug'.
            per_page: Number of results to return (default: 20).
        """
        logger.info("Tool called: github_search_issues query=%s", query)
        svc = ApiServiceGitHubRepos(CONFIG)
        result = svc.search_issues(query=query, per_page=per_page)
        result = result if isinstance(result, list) else []
        logger.info("github_search_issues returned %d result(s)", len(result))
        return [i.__dict__ for i in result]
