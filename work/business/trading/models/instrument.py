from core.web.services.core.json import JsonObject


class ModelStock(JsonObject):
    code: str = None
    name: str = None
    portfolio_percent: str = None
    market_price: float = 0.0
    average_price: float = 0.0
    total_shares: int = 0
    uncommitted_shares: int = 0
    market_value: float = 0.0
    gain_loss_value: float = 0.0
    gain_loss_percentage: float = 0.0
    exchange: str = None

