from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoAlphaVantageExchangeRate:
    """Real-time exchange rate (function=CURRENCY_EXCHANGE_RATE)."""
    from_currency_code: Optional[str] = None
    from_currency_name: Optional[str] = None
    to_currency_code: Optional[str] = None
    to_currency_name: Optional[str] = None
    exchange_rate: Optional[str] = None
    last_refreshed: Optional[str] = None
    time_zone: Optional[str] = None
    bid_price: Optional[str] = None
    ask_price: Optional[str] = None
