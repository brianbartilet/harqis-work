from dataclasses import dataclass, field
from typing import List, Optional


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
