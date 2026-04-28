import base64
from typing import List, Optional

from apps.github.references.web.base_api_service import BaseApiServiceGitHub
from apps.github.references.dto.github import (
    DtoGitHubRepo, DtoGitHubIssue, DtoGitHubPR, DtoGitHubCommit, DtoGitHubBranch,
)


def _map_repo(d: dict) -> DtoGitHubRepo:
    return DtoGitHubRepo(
        id=d.get("id"), name=d.get("name"), full_name=d.get("full_name"),
        description=d.get("description"), private=d.get("private"),
        html_url=d.get("html_url"), clone_url=d.get("clone_url"),
        default_branch=d.get("default_branch"), language=d.get("language"),
        stargazers_count=d.get("stargazers_count"), forks_count=d.get("forks_count"),
        updated_at=d.get("updated_at"),
    )


def _map_issue(d: dict) -> DtoGitHubIssue:
    return DtoGitHubIssue(
        id=d.get("id"), number=d.get("number"), title=d.get("title"),
        state=d.get("state"), body=d.get("body"), html_url=d.get("html_url"),
        user_login=(d.get("user") or {}).get("login"),
        labels=[l.get("name") for l in d.get("labels") or []],
        assignees=[a.get("login") for a in d.get("assignees") or []],
        created_at=d.get("created_at"), updated_at=d.get("updated_at"),
        closed_at=d.get("closed_at"),
    )


def _map_pr(d: dict) -> DtoGitHubPR:
    return DtoGitHubPR(
        id=d.get("id"), number=d.get("number"), title=d.get("title"),
        state=d.get("state"), body=d.get("body"), html_url=d.get("html_url"),
        head_ref=(d.get("head") or {}).get("ref"),
        base_ref=(d.get("base") or {}).get("ref"),
        user_login=(d.get("user") or {}).get("login"),
        merged=d.get("merged"), created_at=d.get("created_at"), updated_at=d.get("updated_at"),
    )


def _map_commit(d: dict) -> DtoGitHubCommit:
    c = d.get("commit") or {}
    author = c.get("author") or {}
    return DtoGitHubCommit(
        sha=d.get("sha"), message=c.get("message"),
        author_name=author.get("name"), author_email=author.get("email"),
        date=author.get("date"), html_url=d.get("html_url"),
    )


def _map_branch(d: dict) -> DtoGitHubBranch:
    return DtoGitHubBranch(
        name=d.get("name"),
        sha=(d.get("commit") or {}).get("sha"),
        protected=d.get("protected"),
    )


class ApiServiceGitHubRepos(BaseApiServiceGitHub):
    """GitHub Repos, Issues, PRs, Commits, Branches, and file content."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def get_authenticated_user(self) -> dict:
        return self._get("/user")

    def list_repos(self, visibility: str = "all", per_page: int = 30) -> List[DtoGitHubRepo]:
        data = self._get("/user/repos", params={"visibility": visibility, "per_page": per_page, "sort": "updated"})
        return [_map_repo(r) for r in (data if isinstance(data, list) else [])]

    def get_repo(self, owner: str, repo: str) -> DtoGitHubRepo:
        return _map_repo(self._get(f"/repos/{owner}/{repo}"))

    def list_issues(self, owner: str, repo: str, state: str = "open", per_page: int = 30) -> List[DtoGitHubIssue]:
        data = self._get(f"/repos/{owner}/{repo}/issues",
                         params={"state": state, "per_page": per_page})
        return [_map_issue(i) for i in (data if isinstance(data, list) else []) if "pull_request" not in i]

    def get_issue(self, owner: str, repo: str, issue_number: int) -> DtoGitHubIssue:
        return _map_issue(self._get(f"/repos/{owner}/{repo}/issues/{issue_number}"))

    def create_issue(self, owner: str, repo: str, title: str,
                     body: str = "", labels: Optional[List[str]] = None) -> DtoGitHubIssue:
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return _map_issue(self._post(f"/repos/{owner}/{repo}/issues", payload))

    def list_pull_requests(self, owner: str, repo: str, state: str = "open",
                           per_page: int = 30) -> List[DtoGitHubPR]:
        data = self._get(f"/repos/{owner}/{repo}/pulls",
                         params={"state": state, "per_page": per_page})
        return [_map_pr(p) for p in (data if isinstance(data, list) else [])]

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> DtoGitHubPR:
        return _map_pr(self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}"))

    def list_commits(self, owner: str, repo: str, branch: str = None,
                     per_page: int = 30) -> List[DtoGitHubCommit]:
        params = {"per_page": per_page}
        if branch:
            params["sha"] = branch
        data = self._get(f"/repos/{owner}/{repo}/commits", params=params)
        return [_map_commit(c) for c in (data if isinstance(data, list) else [])]

    def list_branches(self, owner: str, repo: str) -> List[DtoGitHubBranch]:
        data = self._get(f"/repos/{owner}/{repo}/branches")
        return [_map_branch(b) for b in (data if isinstance(data, list) else [])]

    def get_file_content(self, owner: str, repo: str, path: str, ref: str = None) -> dict:
        params = {}
        if ref:
            params["ref"] = ref
        data = self._get(f"/repos/{owner}/{repo}/contents/{path}", params=params)
        if isinstance(data, dict) and data.get("content"):
            content = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8", errors="replace")
            data = {**data, "decoded_content": content}
        return data

    def search_repos(self, query: str, per_page: int = 20) -> List[DtoGitHubRepo]:
        data = self._get("/search/repositories", params={"q": query, "per_page": per_page})
        return [_map_repo(r) for r in (data.get("items") or [] if isinstance(data, dict) else [])]

    def search_issues(self, query: str, per_page: int = 20) -> List[DtoGitHubIssue]:
        data = self._get("/search/issues", params={"q": query, "per_page": per_page})
        return [_map_issue(i) for i in (data.get("items") or [] if isinstance(data, dict) else [])]
