from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoStripeEvent:
    """Stripe Event object — `GET /v1/events/{id}`.

    Events are the audit trail / webhook history. `data.object` holds the
    full snapshot of the resource at the moment the event fired.
    """
    id: Optional[str] = None
    object: Optional[str] = None
    api_version: Optional[str] = None
    created: Optional[int] = None
    data: Optional[dict] = None
    livemode: Optional[bool] = None
    pending_webhooks: Optional[int] = None
    request: Optional[dict] = None
    type: Optional[str] = None
