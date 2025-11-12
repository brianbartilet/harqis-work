from core.web.services.core.json import JsonObject


class ModelPortfolioItemAAA(JsonObject):
    symbol: str = None
    quantity: int = 0
    sell_pending: int = 0
    buy_pending: int = 0
    available_quantity: int = 0
    average_cost: float = 0.0
    market_value: float = 0.0
    gain_loss_value: float = 0.0
    gain_loss_percentage: float = 0.0
    portfolio_percentage: float = 0.0
    market_price: float = 0.0
    description: str = None
    portfolio_id: str = None
    average_price: float = 0.0
    cost_value: float = 0.0
    currency: str = None
    exchange: str = None
