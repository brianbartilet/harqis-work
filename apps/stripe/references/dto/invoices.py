from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoStripeInvoice:
    """Stripe Invoice object — `GET /v1/invoices/{id}`."""
    id: Optional[str] = None
    object: Optional[str] = None
    account_country: Optional[str] = None
    account_name: Optional[str] = None
    amount_due: Optional[int] = None
    amount_paid: Optional[int] = None
    amount_remaining: Optional[int] = None
    attempt_count: Optional[int] = None
    attempted: Optional[bool] = None
    auto_advance: Optional[bool] = None
    billing_reason: Optional[str] = None
    collection_method: Optional[str] = None
    created: Optional[int] = None
    currency: Optional[str] = None
    customer: Optional[str] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[int] = None
    hosted_invoice_url: Optional[str] = None
    invoice_pdf: Optional[str] = None
    livemode: Optional[bool] = None
    metadata: Optional[dict] = None
    number: Optional[str] = None
    paid: Optional[bool] = None
    period_end: Optional[int] = None
    period_start: Optional[int] = None
    status: Optional[str] = None
    subscription: Optional[str] = None
    subtotal: Optional[int] = None
    tax: Optional[int] = None
    total: Optional[int] = None
