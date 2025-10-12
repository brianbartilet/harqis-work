from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DtoEchoMTGCard:
    emid: Optional[str] = None
    mid: Optional[str] = None
    quantity: int = 1
    language: str = "EN"
    acquired_price: Optional[float] = None
    # compute default at instantiation time (not import time)
    acquired_date: str = field(default_factory=lambda: datetime.today().strftime("%m-%d-%Y"))
    condition: str = "NM"
    foil: int = 0  # keep as int to match your original (0/1)


@dataclass
class DtoDelverLensMTGCard:
    multiverseid: Optional[str] = None
    foil: Optional[int] = None  # keep None/int to mirror your original
    name: Optional[str] = None
