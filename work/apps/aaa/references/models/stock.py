from core.web.services.core.json import JsonObject


class ModelStockAAA(JsonObject):
    symbol: str = None
    description: str = None
    last_traded: str = None
    bid_qty: float = 0.0
    bid: float = 0.0
    offer: float = 0.0
    offer_qty: float = 0.0
    volume: float = 0.0
    value: float = 0.0
    change: float = 0.0
    change_percent: float = 0.0
    prev_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    trades: list = []
    cash_map: dict = {}
    wk_52_hi: float = 0.0
    wk_52_lo: float = 0.0
