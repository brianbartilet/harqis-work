from dataclasses import dataclass
from typing import Optional, List
from dataclasses import dataclass, fields
from typing import Optional, List, Any, Dict

@dataclass
class DtoAccountProperties:
    id: str
    mt4AccountID: Optional[str] = None
    tags: Optional[List[str]] = None

@dataclass
class DtoAccountDetails:
    id: str
    alias: Optional[str] = None
    currency: Optional[str] = None
    balance: Optional[float] = None
    NAV: Optional[str] = None
    marginRate: Optional[float] = None
    openTradeCount: Optional[int] = None
    openPositionCount: Optional[int] = None
    pendingOrderCount: Optional[int] = None
    hedgingEnabled: Optional[bool] = None
    createdTime: Optional[str] = None

@dataclass
class DtoAccountInstruments:
    name = None
    type = None
    displayName = None
    pipLocation = None
    displayLocation = None
    tradeUnitsPrecision = None
    minimumTradeSize = None
    maximumTrailingStopDistance = None
    minimumTrailingStopDistance = None
    maximumPositionSize = None
    maximumOrderUnits = None
    marginRate = None
    guaranteedStopLossOrderMode = None
    tags = []
    financing = {}