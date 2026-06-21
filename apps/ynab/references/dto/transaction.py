from dataclasses import dataclass, field
from typing import List, Optional, Literal


ScheduledFrequency = Literal[
    "never",
    "daily",
    "weekly",
    "everyOtherWeek",
    "twiceAMonth",
    "every4Weeks",
    "monthly",
    "everyOtherMonth",
    "every3Months",
    "every4Months",
    "twiceAYear",
    "yearly",
    "everyOtherYear",
]


@dataclass
class DtoSaveSubTransaction:
    amount: int
    payee_id: Optional[str] = None
    payee_name: Optional[str] = None
    category_id: Optional[str] = None
    memo: Optional[str] = None


@dataclass
class DtoSaveTransaction:
    account_id: str
    date: str                      # ISO format (e.g. "2016-12-01")
    amount: int = 0
    payee_id: Optional[str] = None
    payee_name: Optional[str] = None
    category_id: Optional[str] = None
    memo: Optional[str] = None
    cleared: Optional[str] = None  # cleared | uncleared | reconciled
    approved: bool = False
    flag_color: Optional[str] = None  # red | orange | yellow | green | blue | purple
    import_id: Optional[str] = None
    subtransactions: List[DtoSaveSubTransaction] = field(default_factory=list)


@dataclass
class DtoUpdateTransaction(DtoSaveTransaction):
    id: str = ""


@dataclass
class DtoSaveTransactionsWrapper:
    transaction: Optional[DtoSaveTransaction] = None
    transactions: List[DtoSaveTransaction] = field(default_factory=list)


@dataclass
class DtoSaveScheduledTransaction:
    account_id: str
    date: str                          # first/next date, ISO format (e.g. "2026-12-01")
    amount: int = 0
    payee_id: Optional[str] = None
    payee_name: Optional[str] = None
    category_id: Optional[str] = None
    memo: Optional[str] = None
    flag_color: Optional[str] = None   # red | orange | yellow | green | blue | purple
    frequency: ScheduledFrequency = "monthly"


@dataclass
class DtoUpdateScheduledTransaction(DtoSaveScheduledTransaction):
    id: str = ""
