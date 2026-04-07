from dataclasses import dataclass


@dataclass
class DtoOrgoWorkspace:
    id: str = ''
    name: str = ''
    created_at: str = ''
    computer_count: int = 0


@dataclass
class DtoOrgoCreateWorkspace:
    name: str = ''
