from core.web.services.core.json import JsonObject
from enum import Enum


class EnumTimeInForce(Enum):
    GTC = 'GTC'
    GTD = 'GTD'
    GFD = 'GFD'
    FOK = 'FOK'
    IOC = 'IOC'


class EnumTradeStateFilter(Enum):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'
    CLOSE_WHEN_TRADEABLE = 'CLOSE_WHEN_TRADEABLE'
    ALL = 'ALL'


class DtoClientExtensions(JsonObject):
    id = str
    tag = str
    comment = str


class DtoMarketOrderTradeClose(JsonObject):
    tradeID = str
    clientTradeID = str
    units = str


class DtoMarketOrderPositionCloseout(JsonObject):
    instrument = str
    units = str


class DtoMarketOrderMarginCloseout(JsonObject):
    reason = str


class DtoMarketOrderDelayedTradeClose(JsonObject):
    tradeID = str
    clientTradeID = str
    sourceTransactionID = str


class DtoTakeProfitDetails(JsonObject):
    price = str
    timeInForce = EnumTimeInForce
    gtdTime = str
    clientExtensions = DtoClientExtensions


class DtoStopLossDetails(DtoTakeProfitDetails):
    distance = 0
    guaranteed = None


class DtoGuaranteedStopLossDetails(DtoStopLossDetails):
    distance = 0


class DtoTrailingStopLossDetails(DtoTakeProfitDetails):
    distance = 0


class EnumTransactionType(Enum):
    CREATE = 'CREATE'
    CLOSE = 'CLOSE'
    REOPEN = 'REOPEN'
    CLIENT_CONFIGURE = 'CLIENT_CONFIGURE'
    CLIENT_CONFIGURE_REJECT = 'CLIENT_CONFIGURE_REJECT'
    TRANSFER_FUNDS = 'TRANSFER_FUNDS'
    TRANSFER_FUNDS_REJECT = 'TRANSFER_FUNDS_REJECT'
    MARKET_ORDER = 'MARKET_ORDER'
    MARKET_ORDER_REJECT = 'MARKET_ORDER_REJECT'
    FIXED_PRICE_ORDER = 'FIXED_PRICE_ORDER'
    LIMIT_ORDER = 'LIMIT_ORDER'
    LIMIT_ORDER_REJECT = 'LIMIT_ORDER_REJECT'
    STOP_ORDER = 'STOP_ORDER'
    STOP_ORDER_REJECT = 'STOP_ORDER_REJECT'
    MARKET_IF_TOUCHED_ORDER = 'MARKET_IF_TOUCHED_ORDER'
    MARKET_IF_TOUCHED_ORDER_REJECT = 'MARKET_IF_TOUCHED_ORDER_REJECT'
    TAKE_PROFIT_ORDER = 'TAKE_PROFIT_ORDER'
    TAKE_PROFIT_ORDER_REJECT = 'TAKE_PROFIT_ORDER_REJECT'
    STOP_LOSS_ORDER = 'STOP_LOSS_ORDER'
    STOP_LOSS_ORDER_REJECT = 'STOP_LOSS_ORDER_REJECT'
    GUARANTEED_STOP_LOSS_ORDER = 'GUARANTEED_STOP_LOSS_ORDER'
    GUARANTEED_STOP_LOSS_ORDER_REJECT = 'GUARANTEED_STOP_LOSS_ORDER_REJECT'
    TRAILING_STOP_LOSS_ORDER = 'TRAILING_STOP_LOSS_ORDER'
    TRAILING_STOP_LOSS_ORDER_REJECT = 'TRAILING_STOP_LOSS_ORDER_REJECT'
    ORDER_FILL = 'ORDER_FILL'
    ORDER_CANCEL = 'ORDER_CANCEL'
    ORDER_CANCEL_REJECT = 'ORDER_CANCEL_REJECT'
    ORDER_CLIENT_EXTENSIONS_MODIFY = 'ORDER_CLIENT_EXTENSIONS_MODIFY'
    ORDER_CLIENT_EXTENSIONS_MODIFY_REJECT = 'ORDER_CLIENT_EXTENSIONS_MODIFY_REJECT'
    TRADE_CLIENT_EXTENSIONS_MODIFY = 'TRADE_CLIENT_EXTENSIONS_MODIFY'
    TRADE_CLIENT_EXTENSIONS_MODIFY_REJECT = 'TRADE_CLIENT_EXTENSIONS_MODIFY_REJECT'
    MARGIN_CALL_ENTER = 'MARGIN_CALL_ENTER'
    MARGIN_CALL_EXTEND = 'MARGIN_CALL_EXTEND'
    MARGIN_CALL_EXIT = 'MARGIN_CALL_EXIT'
    DELAYED_TRADE_CLOSURE = 'DELAYED_TRADE_CLOSURE'
    DAILY_FINANCING = 'DAILY_FINANCING'
    DIVIDEND_ADJUSTMENT = 'DIVIDEND_ADJUSTMENT'
    RESET_RESETTABLE_PL = 'RESET_RESETTABLE_PL'


class DtoTransactions(JsonObject):
    id = str
    time = str
    userID = 0
    accountID = str
    batchID = str
    requestID = str


class DtoCreateTransaction(DtoTransactions):
    type = EnumTransactionType
    divisionID = 0
    siteID = 0
    accountUserID = 0
    accountNumber = 0
    homeCurrency = str


class DtoCloseTransaction(DtoTransactions):
    type = EnumTransactionType


class DtoReopenTransaction(DtoTransactions):
    type = EnumTransactionType


class DtoClientConfigureTransaction(DtoTransactions):
    type = EnumTransactionType
    alias = str
    marginRate = str


# TODO: Continue adding dtos https://developer.oanda.com/rest-live-v20/transaction-df/
