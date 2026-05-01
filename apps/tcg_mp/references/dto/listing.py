from dataclasses import dataclass
from typing import Optional
from enum import IntEnum


class ListingStatus(IntEnum):
    OFF = 0
    ON = 1


@dataclass
class DtoListingItem:
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


@dataclass
class DtoWantToBuyListing:
    """One buyer's want-to-buy listing for a product, returned by
    `POST /buy/listed_item_filter`.

    `id` is the want-to-buy record id used as `listing_id` when adding to the
    sell cart via `POST /want_to_buy/cart/add`.
    """
    id: Optional[int] = None
    expdate: Optional[int] = None
    own_listing: Optional[int] = None
    buyer_id: Optional[int] = None
    buyer_name: Optional[str] = None
    buyer_type: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[str] = None
    crd_condition: Optional[str] = None
    crd_foil: Optional[str] = None
    crd_language: Optional[str] = None
    country_code: Optional[str] = None
    listed: Optional[int] = None
    crd_setcode: Optional[str] = None
    suspended: Optional[int] = None
    dropoff_available: Optional[int] = None
    total_bought: Optional[int] = None
