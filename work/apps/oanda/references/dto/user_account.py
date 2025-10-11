from core.web.services.core.json import JsonObject
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class DtoAccountProperties:
    id: str
    mt4AccountID: Optional[str] = None
    tags: Optional[List[str]] = None

class DtoAccountDetails(JsonObject):
    guaranteedStopLossOrderMode = None
    id = None
    balance = None
    openTradeCount = None
    openPositionCount = None
    pendingOrderCount = None
    trades = None
    positions = None
    orders = None


class DtoAccountInstruments(JsonObject):
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