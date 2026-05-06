from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class DtoStripeCharge:
    """Stripe Charge object — `GET /v1/charges/{id}`."""
    id: Optional[str] = None
    object: Optional[str] = None
    amount: Optional[int] = None
    amount_captured: Optional[int] = None
    amount_refunded: Optional[int] = None
    captured: Optional[bool] = None
    created: Optional[int] = None
    currency: Optional[str] = None
    customer: Optional[str] = None
    description: Optional[str] = None
    paid: Optional[bool] = None
    payment_intent: Optional[str] = None
    payment_method: Optional[str] = None
    receipt_email: Optional[str] = None
    receipt_url: Optional[str] = None
    refunded: Optional[bool] = None
    status: Optional[str] = None
    invoice: Optional[str] = None
    metadata: Optional[dict] = None
    failure_message: Optional[str] = None
    failure_code: Optional[str] = None
