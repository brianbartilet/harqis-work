from enum import StrEnum


class WorkflowQueue(StrEnum):
    DEFAULT = "default"
    HUD = "hud"
    TCG = "tcg"
    ADHOC = "adhoc"
