from core.web.services.core.json import JsonObject
from enum import Enum


class TradingConditionsStatus(Enum):
    NEW = 'New'
    OPEN = 'Open'
    PENDING_BUY = 'Pending Buy'
    PENDING_SELL = 'Pending Sell'
    CLOSED = 'Closed'
    CANCELLED = 'Cancelled'
    INCOMPLETE_PENDING_STOP_ORDERS = 'Incomplete Stop'
    INCOMPLETE_PENDING_PROFIT_ORDERS = 'Incomplete Profit'
    INCOMPLETE_PENDING_ORDERS = 'Incomplete Orders'


class DtoTradeManager(JsonObject):
    status = str
    direction = str
    net_profit = float
    risk_reward = float

    create_order = object
    stop_order = object
    profit_order = object
    trailing_order = object

    current_orders = []
    portfolio = []
    portfolio_target = object
    stock_data = object
    system_name = str

    last_success_order = object
    date = str