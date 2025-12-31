from dataclasses import dataclass, asdict
from typing import Literal


AccountType = Literal[
    "checking",
    "savings",
    "creditCard",
    "cash",
    "lineOfCredit",
    "otherAsset",
    "otherLiability",
]


@dataclass
class DtoSaveAccount:
    name: str | None = None
    type: AccountType = "savings"
    balance: float = 0.0


@dataclass
class DtoSaveAccountWrapper:
    account: DtoSaveAccount

    def to_dict(self) -> dict:
        return asdict(self)
