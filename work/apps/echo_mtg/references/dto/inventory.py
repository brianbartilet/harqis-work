from dataclasses import dataclass, fields
from typing import Any, Dict, Optional


@dataclass
class DtoPortfolioStats:
    acquired_value: Optional[float] = None
    current_value: Optional[float] = None
    current_high_value_value: Optional[float] = None
    current_value_low: Optional[float] = None
    current_value_market: Optional[float] = None

    total_items: Optional[int] = None
    total_cards: Optional[int] = None
    total_foils: Optional[int] = None
    total_nonfoils: Optional[int] = None
    total_sealed: Optional[int] = None
    sealed_value: Optional[float] = None
    total_packs: Optional[int] = None
    packs_value: Optional[float] = None

    total_mythic: Optional[int] = None
    total_rare: Optional[int] = None
    total_uncommon: Optional[int] = None
    total_common: Optional[int] = None

    currency_symbol: Optional[str] = None
    total_profit: Optional[float] = None
    change_value: Optional[float] = None
    percentage_html: Optional[str] = None

    user_items_stored: Optional[int] = None
    user_items_cap: Optional[int] = None
    user_items_cap_percentage_used: Optional[float] = None

    user: Optional[Dict[str, Any]] = None  # replace with a DTO later if desired
