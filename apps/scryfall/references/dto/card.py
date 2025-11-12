from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional


@dataclass
class DtoScryFallCard:
    """
    Flat DTO for a Scryfall card response.

    This class is intentionally minimal and dict-friendly:
    - Top-level fields are simple scalars or lists.
    - Nested objects (e.g., image_uris, legalities, prices) are stored as raw dicts.
    - Unknown keys in the source dict are ignored during deserialization.

    Use `from_dict` for tolerant construction from an API payload.
    """

    # --- Core identifiers ---
    object: Optional[str] = None
    id: Optional[str] = None
    oracle_id: Optional[str] = None
    multiverse_ids: Optional[List[int]] = None
    arena_id: Optional[int] = None
    tcgplayer_id: Optional[int] = None
    cardmarket_id: Optional[int] = None

    # --- Metadata / links ---
    name: Optional[str] = None
    lang: Optional[str] = None
    released_at: Optional[str] = None  # keep as string for simplicity
    uri: Optional[str] = None
    scryfall_uri: Optional[str] = None
    layout: Optional[str] = None
    highres_image: Optional[bool] = None
    image_status: Optional[str] = None

    # --- Nested blobs kept as dicts ---
    image_uris: Optional[Dict[str, Any]] = None
    legalities: Optional[Dict[str, Any]] = None
    prices: Optional[Dict[str, Any]] = None
    related_uris: Optional[Dict[str, Any]] = None
    purchase_uris: Optional[Dict[str, Any]] = None

    # --- Rules & color info ---
    mana_cost: Optional[str] = None
    cmc: Optional[float] = None
    type_line: Optional[str] = None
    oracle_text: Optional[str] = None
    colors: Optional[List[str]] = None
    color_identity: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    produced_mana: Optional[List[str]] = None

    # --- Flags / set info ---
    games: Optional[List[str]] = None
    reserved: Optional[bool] = None
    game_changer: Optional[bool] = None
    foil: Optional[bool] = None            # print availability from API
    nonfoil: Optional[bool] = None         # print availability from API
    finishes: Optional[List[str]] = None
    oversized: Optional[bool] = None
    promo: Optional[bool] = None
    reprint: Optional[bool] = None
    variation: Optional[bool] = None
    set_id: Optional[str] = None
    set: Optional[str] = None
    set_name: Optional[str] = None
    set_type: Optional[str] = None
    set_uri: Optional[str] = None
    set_search_uri: Optional[str] = None
    scryfall_set_uri: Optional[str] = None
    rulings_uri: Optional[str] = None
    prints_search_uri: Optional[str] = None
    collector_number: Optional[str] = None
    digital: Optional[bool] = None
    rarity: Optional[str] = None
    card_back_id: Optional[str] = None
    artist: Optional[str] = None
    artist_ids: Optional[List[str]] = None
    illustration_id: Optional[str] = None
    border_color: Optional[str] = None
    frame: Optional[str] = None
    frame_effects: Optional[List[str]] = None
    security_stamp: Optional[str] = None
    full_art: Optional[bool] = None
    textless: Optional[bool] = None
    booster: Optional[bool] = None
    story_spotlight: Optional[bool] = None
    promo_types: Optional[List[str]] = None
    edhrec_rank: Optional[int] = None
    penny_rank: Optional[int] = None

    # --- Convenience: keep raw if desired ---
    raw: Optional[Dict[str, Any]] = None