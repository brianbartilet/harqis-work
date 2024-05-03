from core.web.services.core.json import JsonObject


class ModelAccountAAA(JsonObject):
    cash_balance: float = 0.0
    available_cash: float = 0.0
    pending_cash: float = 0.0
    available_to_withdraw: float = 0.0
    unsettled_sales: float = 0.0
    payable_amount: float = 0.0
    od_limit: float = 0.0
    portfolio_value: float = 0.0
    total_portfolio_value: float = 0.0

