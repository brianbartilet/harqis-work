from core.web.services.core.json import JsonObject
from enum import Enum


class Order(Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class OrderType(Enum):
    LIMIT = 'LIMIT'


class OrderValidUntil(Enum):
    DAY = 'DAY'
    GTD = 'GTD'
    GTC = 'GTC'
    IOC = 'IOC'


class CreateOrder(JsonObject):
    order = Order
    order_type = OrderType
    valid_until = OrderValidUntil
