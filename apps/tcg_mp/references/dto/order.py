from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


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

@dataclass
class DtoOrderSummaryByStatus:
    """Represents a collection of order summaries filtered by status."""
    data: Optional[List[DtoOrderSummary]] = None
    status: Optional[int] = None

class EnumTcgOrderStatus(Enum):
    ALL=(-2, ""),
    PENDING_DROP_OFF = (1, "Pending Drop Off")
    ARRIVED_BRANCH = (7, "Arrived_Branch")
    DROPPED = (6, "Dropped Off")
    CANCELLED = (4, "Cancelled")
    PICKED_UP = (2, "Picked Up")
    SHIPPED = (3, "Shipped")

    @property
    def code(self):
        return self.value[0]

    @property
    def label(self):
        return self.value[1]

    @classmethod
    def from_code(cls, code: int):
        for status in cls:
            if status.code == code:
                return status
        return None  # or raise ValueError