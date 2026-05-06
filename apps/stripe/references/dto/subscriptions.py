from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoStripeSubscription:
    """Stripe Subscription object — `GET /v1/subscriptions/{id}`."""
    id: Optional[str] = None
    object: Optional[str] = None
    application: Optional[str] = None
    automatic_tax: Optional[dict] = None
    billing_cycle_anchor: Optional[int] = None
    cancel_at: Optional[int] = None
    cancel_at_period_end: Optional[bool] = None
    canceled_at: Optional[int] = None
    cancellation_details: Optional[dict] = None
    collection_method: Optional[str] = None
    created: Optional[int] = None
    currency: Optional[str] = None
    current_period_end: Optional[int] = None
    current_period_start: Optional[int] = None
    customer: Optional[str] = None
    days_until_due: Optional[int] = None
    default_payment_method: Optional[str] = None
    description: Optional[str] = None
    discount: Optional[dict] = None
    ended_at: Optional[int] = None
    items: Optional[dict] = None
    latest_invoice: Optional[str] = None
    livemode: Optional[bool] = None
    metadata: Optional[dict] = None
    next_pending_invoice_item_invoice: Optional[int] = None
    pause_collection: Optional[dict] = None
    payment_settings: Optional[dict] = None
    pending_invoice_item_interval: Optional[dict] = None
    pending_setup_intent: Optional[str] = None
    pending_update: Optional[dict] = None
    schedule: Optional[str] = None
    start_date: Optional[int] = None
    status: Optional[str] = None
    test_clock: Optional[str] = None
    transfer_data: Optional[dict] = None
    trial_end: Optional[int] = None
    trial_start: Optional[int] = None
