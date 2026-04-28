from dataclasses import dataclass
from typing import Optional, List


@dataclass
class DtoGitHubRepo:
    id: Optional[int] = None
    name: Optional[str] = None
    full_name: Optional[str] = None
    description: Optional[str] = None
    private: Optional[bool] = None
    html_url: Optional[str] = None
    clone_url: Optional[str] = None
    default_branch: Optional[str] = None
    language: Optional[str] = None
    stargazers_count: Optional[int] = None
    forks_count: Optional[int] = None
    updated_at: Optional[str] = None


@dataclass
class DtoGitHubIssue:
    id: Optional[int] = None
    number: Optional[int] = None
    title: Optional[str] = None
    state: Optional[str] = None
    body: Optional[str] = None
    html_url: Optional[str] = None
    user_login: Optional[str] = None
    labels: Optional[List[str]] = None
    assignees: Optional[List[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    closed_at: Optional[str] = None


@dataclass
class DtoGitHubPR:
    id: Optional[int] = None
    number: Optional[int] = None
    title: Optional[str] = None
    state: Optional[str] = None
    body: Optional[str] = None
    html_url: Optional[str] = None
    head_ref: Optional[str] = None
    base_ref: Optional[str] = None
    user_login: Optional[str] = None
    merged: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class DtoGitHubCommit:
    sha: Optional[str] = None
    message: Optional[str] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    date: Optional[str] = None
    html_url: Optional[str] = None


@dataclass
class DtoGitHubBranch:
    name: Optional[str] = None
    sha: Optional[str] = None
    protected: Optional[bool] = None
