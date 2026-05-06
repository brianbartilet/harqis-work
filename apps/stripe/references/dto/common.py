from dataclasses import dataclass, field
from typing import Optional, List, Any


@dataclass
class DtoStripeListResult:
    """Generic Stripe list response envelope.

    Stripe returns paginated lists as `{object: 'list', data: [...], has_more, url}`.
    `data` items are typed per-resource by the calling service.
    """
    object: Optional[str] = None
    data: List[Any] = field(default_factory=list)
    has_more: Optional[bool] = None
    url: Optional[str] = None
