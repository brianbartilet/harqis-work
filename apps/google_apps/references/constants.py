from enum import Enum


class ScheduleCategory(str, Enum):
    PINNED = "Pinned"
    PLAY = "Mischief | Misdirection | Play"
    FINANCE = "Finance | Investing | Business"
    WORK = "Career | Work"
    ORGANIZE = "Organization | Everyman Skills"
    DEACTIVATED = "Deactivated"

    def __str__(self) -> str:
        return self.value
