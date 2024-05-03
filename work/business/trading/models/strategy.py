from core.web.services.core.json import JsonObject


class DtoPSEIScreenerStrategy(JsonObject):
    strategy_name = None
    stock_name = None
    signal_date = None
    growth_percent_from_signal_date = 0
    days_elapsed = 0
    days_elapsed_to_stop = 0
    days_elapsed_to_target = 0
    risk_reward = 0


class DtoForexStrategy(JsonObject):
    id = None
    instrument_date = dict
