from core.web.services.core.json import JsonObject
from work.business.trading.models.order import Order, OrderType, OrderValidUntil
from enum import Enum
from dataclasses import dataclass


class OrderStatusAAA(Enum):
    PENDING_TRIGGER = 'Pending Trigger'
    QUEUED = 'Queued'
    FILLED = 'Filled'


class ConditionsOrderFieldAAA(Enum):
    LAST_PRICE = 'Last Price'
    NONE = 'None'


class ConditionsOrderTriggerAAA(Enum):
    GREATER_THAN_OR_EQUAL_TO = 'Greater Than Or Equal'
    LESS_THAN_OR_EQUAL_TO = 'Less Than Or equal'
    EQUAL = 'Equal'


@dataclass
class ModelCreateOrderAAA(JsonObject):
    stock_name: str = None
    transaction: str = Order.BUY.value

    order_type: str = OrderType.LIMIT.value
    quantity: int = 0
    good_until: str = OrderValidUntil.GTC.value
    price: float = 0.0

    condition_field: str = ConditionsOrderFieldAAA.NONE.value
    condition_price: float = 0.0
    condition_trigger: str = ConditionsOrderTriggerAAA.EQUAL.value
    condition_expiry_date: str = None  # MM/DD/YYYY

    created: bool = False
    order_value: float = 0.0
    total_fees: float = 0.0
    net_value: float = 0.0


@dataclass
class ModelOrderAAA(ModelCreateOrderAAA):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    id: str = None
    status: int = 0
    filled_quantity: int = 0
    pending_quantity: int = 0
    average_price: float = 0.0
    order_date: str = None
    condition_order_id: int = 0
    exchange: str = None
    distance: float = 0.0
