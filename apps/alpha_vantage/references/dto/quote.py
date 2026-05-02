from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoAlphaVantageGlobalQuote:
    """Single-symbol latest quote (function=GLOBAL_QUOTE)."""
    symbol: Optional[str] = None
    open: Optional[str] = None
    high: Optional[str] = None
    low: Optional[str] = None
    price: Optional[str] = None
    volume: Optional[str] = None
    latest_trading_day: Optional[str] = None
    previous_close: Optional[str] = None
    change: Optional[str] = None
    change_percent: Optional[str] = None


@dataclass
class DtoAlphaVantageSymbolMatch:
    """One row of function=SYMBOL_SEARCH bestMatches."""
    symbol: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    region: Optional[str] = None
    market_open: Optional[str] = None
    market_close: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    match_score: Optional[str] = None
