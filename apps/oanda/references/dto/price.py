from core.web.services.core.json import JsonObject


class DtoPrice(JsonObject):
    asks = []
    bids = []
    closeoutAsk = None
    closeoutBid = None
    data = None
    instrument = None
    quoteHomeConversionFactors = None
    status = None
    time = None
    type = None
    unitsAvailable = None
