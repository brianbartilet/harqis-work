from core.web.services.core.json import JsonObject
from enum import Enum

from apps.oanda.references.dto.transactions import \
    DtoClientExtensions, DtoMarketOrderTradeClose, DtoMarketOrderPositionCloseout, \
    DtoMarketOrderMarginCloseout, DtoMarketOrderDelayedTradeClose, DtoTakeProfitDetails, \
    DtoStopLossDetails, DtoGuaranteedStopLossDetails, DtoTrailingStopLossDetails, EnumTimeInForce


class EnumOrderState(Enum):
    PENDING = 'PENDING'
    FILLED = 'FILLED'
    TRIGGERED = 'TRIGGERED'
    CANCELLED = 'CANCELLED'




class EnumOrderType(Enum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'
    STOP = 'STOP'
    MARKET_IF_TOUCHED = 'MARKET_IF_TOUCHED'
    TAKE_PROFIT = 'TAKE_PROFIT'
    STOP_LOSS = 'STOP_LOSS'
    TRAILING_STOP_LOSS = 'TRAILING_STOP_LOSS'
    FIXED_PRICE = 'FIXED_PRICE'


class EnumOrderPositionFill(Enum):
    OPEN_ONLY = 'OPEN_ONLY'
    REDUCE_FIRST = 'REDUCE_FIRST'
    REDUCE_ONLY = 'REDUCE_ONLY'
    DEFAULT = 'DEFAULT'


class EnumOrderTriggerCondition(Enum):
    DEFAULT = 'DEFAULT'
    INVERSE = 'INVERSE'
    BID = 'BID'
    ASK = 'ASK'
    MID = 'MID'


class DtoOrder(JsonObject):
    id = str
    createTime = str
    state = EnumOrderState
    clientExtensions = DtoClientExtensions


class DtoMarketOrder(DtoOrder):
    type = EnumOrderType
    instrument = str
    units = 0
    timeInForce = EnumTimeInForce
    priceBound = str
    positionFill = EnumOrderPositionFill
    tradeClose = DtoMarketOrderTradeClose
    longPositionCloseout = DtoMarketOrderPositionCloseout
    shortPositionCloseout = DtoMarketOrderPositionCloseout
    marginCloseout = DtoMarketOrderMarginCloseout
    delayedTradeClose = DtoMarketOrderDelayedTradeClose
    takeProfitOnFill = DtoTakeProfitDetails
    stopLossOnFill = DtoStopLossDetails
    guaranteedStopLossOnFill = DtoGuaranteedStopLossDetails
    trailingStopLossOnFill = DtoTrailingStopLossDetails
    tradeClientExtensions = DtoClientExtensions
    fillingTransactionID = str
    filledTime = str
    tradeOpenedID = str
    tradeReducedID = str
    tradeClosedIDs = []
    cancellingTransactionID = str
    cancelledTime = str


class DtoFixedPriceOrder(DtoMarketOrder):
    price = str
    tradeState = str


class DtoFixedLimitOrder(DtoMarketOrder):
    price = str
    gtdTime = str
    triggerCondition = EnumOrderTriggerCondition,
    replacesOrderID = str
    replacedByOrderID = str


class DtoStopOrder(DtoFixedLimitOrder):
    ...


class DtoMarketIfTouchedOrder(DtoFixedLimitOrder):
    initialMarketPrice = str


class DtoTakeProfitOrder(DtoMarketOrder):
    tradeID = str
    clientTradeID = str
    price = str
    gtdTime = str
    triggerCondition = EnumOrderTriggerCondition,
    replacesOrderID = str
    replacedByOrderID = str


class DtoStopLossOrder(DtoTakeProfitOrder):
    guaranteedExecutionPremium = None
    distance = str
    guaranteed = None


class DtoGuaranteedStopLossOrder(DtoStopLossOrder):
    ...


class DtoTrailingStopLossOrder(DtoStopLossOrder):
    trailingStopValue = str
