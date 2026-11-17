from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class DtoIbkrTrade:
    """One execution from a Flex statement (<TradeConfirm> or execution-level <Trade>)."""
    trade_id: Optional[str] = None          # tradeID (same in Trade Confirmation and Activity reports), else execID
    account_id: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    asset_category: Optional[str] = None    # STK, OPT, FUT, CASH, ...
    side: Optional[str] = None              # BUY / SELL
    quantity: Optional[float] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    amount: Optional[float] = None
    commission: Optional[float] = None
    commission_currency: Optional[str] = None
    exchange: Optional[str] = None
    order_type: Optional[str] = None
    order_id: Optional[str] = None          # IBKR order ID — groups the fills of one order
    listing_exchange: Optional[str] = None  # primary listing, e.g. SGX, NASDAQ, LSEETF
    sub_category: Optional[str] = None      # e.g. ETF, COMMON, REIT (when the query includes it)
    trade_time: Optional[datetime] = None   # as reported by IBKR (no timezone conversion)

    @property
    def trade_date(self):
        return self.trade_time.date() if self.trade_time else None


@dataclass
class DtoIbkrCashTransaction:
    """One cash transaction from a Flex statement (<CashTransaction>), e.g. a deposit."""
    transaction_id: Optional[str] = None
    account_id: Optional[str] = None
    type: Optional[str] = None              # e.g. 'Deposits/Withdrawals', 'Dividends'
    symbol: Optional[str] = None            # set for dividends / withholding tax
    action_id: Optional[str] = None         # corporate action — links a dividend to its tax rows
    ex_date: Optional[str] = None           # dividend ex-date (YYYYMMDD as reported)
    description: Optional[str] = None
    currency: Optional[str] = None
    amount: Optional[float] = None          # positive = money in, negative = money out
    fx_rate_to_base: Optional[float] = None
    date_time: Optional[datetime] = None
    settle_date: Optional[str] = None

    @property
    def date(self):
        return self.date_time.date() if self.date_time else None
