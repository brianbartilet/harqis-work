from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoStripePaymentIntent:
    """Stripe PaymentIntent object — `GET /v1/payment_intents/{id}`."""
    id: Optional[str] = None
    object: Optional[str] = None
    amount: Optional[int] = None
    amount_capturable: Optional[int] = None
    amount_received: Optional[int] = None
    application: Optional[str] = None
    automatic_payment_methods: Optional[dict] = None
    canceled_at: Optional[int] = None
    cancellation_reason: Optional[str] = None
    capture_method: Optional[str] = None
    client_secret: Optional[str] = None
    confirmation_method: Optional[str] = None
    created: Optional[int] = None
    currency: Optional[str] = None
    customer: Optional[str] = None
    description: Optional[str] = None
    invoice: Optional[str] = None
    last_payment_error: Optional[dict] = None
    livemode: Optional[bool] = None
    metadata: Optional[dict] = None
    payment_method: Optional[str] = None
    payment_method_types: Optional[list] = None
    receipt_email: Optional[str] = None
    review: Optional[str] = None
    setup_future_usage: Optional[str] = None
    shipping: Optional[dict] = None
    statement_descriptor: Optional[str] = None
    status: Optional[str] = None
