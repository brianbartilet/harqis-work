from dataclasses import dataclass
from core.web.services.core.json import  JsonObject


@dataclass
class DtoNotesInformation(JsonObject):
    scryfall_gui: str
    tcgplayer_id: int = 0
    tcg_mp_card_id: int = 0
    tcg_mp_listing_id: int = 0
    tcg_mp_selling_price: float = 0
    tcg_mp_smart_pricing: float = 0
    tcg_price: float = 0
    last_updated: str = ''
    message: str = ''
    error: str = ''
    function: str = ''

