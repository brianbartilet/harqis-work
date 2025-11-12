from dataclasses import dataclass
from typing import Optional


@dataclass
class ListingItem:
    """Represents a single card listing record."""
    listing_id: Optional[int] = None
    product_id: Optional[int] = None
    name: Optional[str] = None
    crd_setcode: Optional[str] = None
    setname: Optional[str] = None
    crd_rarity: Optional[str] = None
    own_listing: Optional[int] = None
    quantity: Optional[int] = None
    auction_quantity: Optional[int] = None
    price: Optional[str] = None
    crd_language: Optional[str] = None
    crd_condition: Optional[str] = None
    crd_foil: Optional[str] = None
    crd_signed: Optional[int] = None
    crd_altered: Optional[str] = None
    country_code: Optional[str] = None
    image: Optional[str] = None
    crd_foil_type: Optional[str] = None
    created_date: Optional[str] = None
    front_img: Optional[str] = None
    back_img: Optional[str] = None
