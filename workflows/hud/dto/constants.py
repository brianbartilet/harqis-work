from enum import Enum


class ScheduleCategory(str, Enum):
    PINNED = "Pinned"
    PLAY = "Mischief | Misdirection | Play"
    FINANCE = "Finance | Investing | Business"

    def __str__(self) -> str:
        return self.value
