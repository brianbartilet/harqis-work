from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional


@dataclass
class DtoJusttcgVariant:
    """A single priced variant of a card (a condition + printing + language).

    This is where all pricing and analytics live. Field names match the JustTCG
    JSON response exactly (mostly camelCase) so the framework deserializer can
    map them directly — do not "pythonise" them.

    The variant ``id`` has the format ``{cardId}_{condition}_{printing}`` and can
    be passed back as ``variantId`` for the fastest single lookup.
    """
    # --- identity ---
    id: Optional[str] = None
    condition: Optional[str] = None
    printing: Optional[str] = None
    language: Optional[str] = None
    tcgplayerSkuId: Optional[str] = None

    # --- current price ---
    price: Optional[float] = None
    lastUpdated: Optional[int] = None          # unix timestamp of last price refresh

    # --- 24h analytics ---
    priceChange24hr: Optional[float] = None    # % change over 24h

    # --- 7d analytics ---
    priceChange7d: Optional[float] = None
    avgPrice: Optional[float] = None           # weekly (7d) average price
    minPrice7d: Optional[float] = None
    maxPrice7d: Optional[float] = None
    stddevPopPrice7d: Optional[float] = None
    covPrice7d: Optional[float] = None         # coefficient of variation
    iqrPrice7d: Optional[float] = None         # interquartile range
    trendSlope7d: Optional[float] = None       # linear-regression trend
    priceChangesCount7d: Optional[int] = None
    priceHistory: Optional[List[Dict[str, Any]]] = None   # [{price, timestamp}, ...]

    # --- 30d analytics ---
    priceChange30d: Optional[float] = None
    avgPrice30d: Optional[float] = None
    minPrice30d: Optional[float] = None
    maxPrice30d: Optional[float] = None
    stddevPopPrice30d: Optional[float] = None
    covPrice30d: Optional[float] = None
    iqrPrice30d: Optional[float] = None
    trendSlope30d: Optional[float] = None
    priceChangesCount30d: Optional[int] = None
    priceRelativeTo30dRange: Optional[float] = None       # 0..1 position within 30d range

    # --- 90d analytics ---
    priceChange90d: Optional[float] = None
    avgPrice90d: Optional[float] = None
    minPrice90d: Optional[float] = None
    maxPrice90d: Optional[float] = None
    priceRelativeTo90dRange: Optional[float] = None

    # --- long-term ---
    minPrice1y: Optional[float] = None
    maxPrice1y: Optional[float] = None
    minPriceAllTime: Optional[float] = None
    minPriceAllTimeDate: Optional[str] = None             # ISO 8601
    maxPriceAllTime: Optional[float] = None
    maxPriceAllTimeDate: Optional[str] = None             # ISO 8601


@dataclass
class DtoJusttcgCard:
    """A card and its priced variants. Returned by ``GET``/``POST`` ``/cards``.

    Pricing is stored per-variant in ``variants``; the card itself carries only
    identity/metadata. ``variants`` is kept as a list of raw dicts because the
    framework deserializer does not recurse into nested DTOs — call
    :meth:`variant_dtos` for typed :class:`DtoJusttcgVariant` access.
    """
    id: Optional[str] = None                  # the "cardId"
    name: Optional[str] = None
    game: Optional[str] = None
    set: Optional[str] = None                 # set id
    set_name: Optional[str] = None
    number: Optional[str] = None
    tcgplayerId: Optional[str] = None
    mtgjsonId: Optional[str] = None
    scryfallId: Optional[str] = None
    rarity: Optional[str] = None
    details: Optional[str] = None
    variants: Optional[List[Dict[str, Any]]] = None

    def variant_dtos(self) -> List["DtoJusttcgVariant"]:
        """Return ``variants`` as typed :class:`DtoJusttcgVariant` objects."""
        known = {f.name for f in fields(DtoJusttcgVariant)}
        out: List[DtoJusttcgVariant] = []
        for v in (self.variants or []):
            if isinstance(v, dict):
                out.append(DtoJusttcgVariant(**{k: val for k, val in v.items() if k in known}))
        return out
