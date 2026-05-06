from dataclasses import dataclass, field
from typing import Optional, List, Any


@dataclass
class DtoStripeMoney:
    """Single-currency money amount inside a balance bucket."""
    amount: Optional[int] = None       # smallest unit (cents)
    currency: Optional[str] = None     # ISO-4217 lowercase, e.g. 'usd'
    source_types: Optional[dict] = None


@dataclass
class DtoStripeBalance:
    """Account balance snapshot — `GET /v1/balance`."""
    object: Optional[str] = None
    available: List[DtoStripeMoney] = field(default_factory=list)
    pending: List[DtoStripeMoney] = field(default_factory=list)
    livemode: Optional[bool] = None
    instant_available: Optional[List[DtoStripeMoney]] = None


@dataclass
class DtoStripeBalanceTransaction:
    """A single entry in the balance ledger (charge, payout, fee, refund, …)."""
    id: Optional[str] = None
    object: Optional[str] = None
    amount: Optional[int] = None
    available_on: Optional[int] = None
    created: Optional[int] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    fee: Optional[int] = None
    net: Optional[int] = None
    reporting_category: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    type: Optional[str] = None
