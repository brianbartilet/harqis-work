from dataclasses import dataclass, field
from typing import List, Optional, Any


@dataclass
class DtoJiraProject:
    id: Optional[str] = None
    key: Optional[str] = None
    name: Optional[str] = None
    project_type_key: Optional[str] = None
    style: Optional[str] = None
    url: Optional[str] = None
    self_url: Optional[str] = None


@dataclass
class DtoJiraIssueType:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    subtask: Optional[bool] = None


@dataclass
class DtoJiraUser:
    account_id: Optional[str] = None
    display_name: Optional[str] = None
    email_address: Optional[str] = None
    active: Optional[bool] = None
    account_type: Optional[str] = None
    self_url: Optional[str] = None


@dataclass
class DtoJiraIssueFields:
    summary: Optional[str] = None
    description: Optional[Any] = None
    status: Optional[Any] = None
    priority: Optional[Any] = None
    assignee: Optional[Any] = None
    reporter: Optional[Any] = None
    issuetype: Optional[Any] = None
    project: Optional[Any] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    due_date: Optional[str] = None
    labels: Optional[List[str]] = field(default_factory=list)
    components: Optional[List[Any]] = field(default_factory=list)


@dataclass
class DtoJiraIssue:
    id: Optional[str] = None
    key: Optional[str] = None
    self_url: Optional[str] = None
    fields: Optional[DtoJiraIssueFields] = None


@dataclass
class DtoJiraComment:
    id: Optional[str] = None
    author: Optional[Any] = None
    body: Optional[Any] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    self_url: Optional[str] = None
