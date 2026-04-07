from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoOrgoComputer:
    id: str = ''
    name: str = ''
    workspace_id: str = ''
    os: str = 'linux'
    ram: int = 4
    cpu: int = 2
    gpu: str = 'none'
    resolution: str = '1280x720x24'
    status: str = ''
    auto_stop_minutes: Optional[int] = None
    url: str = ''
    created_at: str = ''


@dataclass
class DtoOrgoCreateComputer:
    workspace_id: str = ''
    name: str = ''
    os: str = 'linux'
    ram: int = 4
    cpu: int = 2
    gpu: str = 'none'
    resolution: str = '1280x720x24'
    auto_stop_minutes: Optional[int] = None


@dataclass
class DtoOrgoVncPassword:
    password: str = ''


@dataclass
class DtoOrgoBashResult:
    output: str = ''
    success: bool = False


@dataclass
class DtoOrgoFile:
    id: str = ''
    filename: str = ''
    size_bytes: int = 0
    content_type: str = ''
    created_at: str = ''
