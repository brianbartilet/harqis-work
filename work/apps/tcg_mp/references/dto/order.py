from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoOrderSummary:
    """Represents a summarized customer order record."""
    id: Optional[int] = None
    order_id: Optional[str] = None
    customer_username: Optional[str] = None
    grand_total: Optional[str] = None
    shipping_method: Optional[str] = None
    last_updated: Optional[str] = None
    created_date: Optional[str] = None
    quantity: Optional[int] = None
    first_item: Optional[str] = None
    image: Optional[str] = None
    is_transfer: Optional[int] = None
    is_buy_voucher: Optional[int] = None
    crd_foil_type: Optional[str] = None