from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoStripeCustomer:
    """Stripe Customer object — `GET /v1/customers/{id}`."""
    id: Optional[str] = None
    object: Optional[str] = None
    address: Optional[dict] = None
    balance: Optional[int] = None
    created: Optional[int] = None
    currency: Optional[str] = None
    default_source: Optional[str] = None
    delinquent: Optional[bool] = None
    description: Optional[str] = None
    discount: Optional[dict] = None
    email: Optional[str] = None
    invoice_prefix: Optional[str] = None
    invoice_settings: Optional[dict] = None
    livemode: Optional[bool] = None
    metadata: Optional[dict] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    preferred_locales: Optional[list] = None
    shipping: Optional[dict] = None
    tax_exempt: Optional[str] = None
