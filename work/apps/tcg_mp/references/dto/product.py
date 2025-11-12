from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ChartPoint:
    """Represents a single data point in the card's price chart."""
    date: str
    avgr: str


@dataclass
class CardData:
    """Represents a single card record in the API response."""
    name: Optional[str] = None
    text: Optional[str] = None
    image: Optional[str] = None
    category_id: Optional[int] = None
    type: Optional[int] = None
    crd_foil_type: Optional[str] = None
    crd_finishes: Optional[str] = None
    crd_setcode: Optional[str] = None
    crd_setname: Optional[str] = None
    crd_rarity: Optional[str] = None
    crd_printings: Optional[str] = None
    card_id: Optional[str] = None
    available_item: Optional[int] = None
    price_from: Optional[str] = None
    day1: Optional[str] = None
    day7: Optional[str] = None
    day30: Optional[str] = None
    foiled: Optional[int] = None
    chart: Optional[List[ChartPoint]] = None
    language: Optional[List[str]] = None


@dataclass
class CardResponse:
    """Top-level response wrapper for card data."""
    data: Optional[List[CardData]] = None
