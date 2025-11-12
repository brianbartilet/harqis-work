from core.web.services.core.json import JsonObject

from apps.oanda.references.dto.orders import \
    EnumOrderType, EnumOrderTriggerCondition, EnumTimeInForce, EnumOrderPositionFill


from apps.oanda.references.dto.transactions import \
    DtoGuaranteedStopLossDetails, DtoTakeProfitDetails, DtoStopLossDetails, \
    DtoClientExtensions, DtoTrailingStopLossDetails


class DtoOrderRequest(JsonObject):
    type = EnumOrderType
    instrument = str
    units = str
    timeInForce = EnumTimeInForce
    priceBound = str
    positionFill = EnumOrderPositionFill
    clientExtensions = DtoClientExtensions
    takeProfitOnFill = DtoTakeProfitDetails
    stopLossOnFill = DtoStopLossDetails
    trailingStopLossOnFill = DtoTrailingStopLossDetails
    tradeClientExtensions = DtoClientExtensions


class DtoMarketOrderRequest(DtoOrderRequest):
    guaranteedStopLossOnFill= DtoGuaranteedStopLossDetails,


class DtoLimitOrderRequest(DtoOrderRequest):
    price = str
    gtdTime = str
    triggerCondition = EnumOrderTriggerCondition
    guaranteedStopLossOnFill = DtoGuaranteedStopLossDetails


class DtoStopOrderRequest(DtoLimitOrderRequest):
    ...


class DtoMarketIfTouchedOrderRequest(DtoLimitOrderRequest):
    ...


class DtoTakeProfitOrderRequest(DtoOrderRequest):
    tradeID = str
    clientTradeID = str
    price = str
    gtdTime = str
    triggerCondition = EnumOrderTriggerCondition


class DtoStopLossOrderRequest(DtoTakeProfitOrderRequest):
    distance = str
    guaranteed = None


class DtoGuaranteedStopLossOrderRequest(DtoStopLossOrderRequest):
    ...


class DtoTrailingStopLossOrderRequest(DtoStopLossOrderRequest):
    ...