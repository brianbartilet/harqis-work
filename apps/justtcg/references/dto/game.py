from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoJusttcgGame:
    """A supported trading-card game (Pokémon, Magic, Yu-Gi-Oh!, Lorcana, …).

    Returned by ``GET /games``. The ``id`` is the stable slug used as the
    ``game`` query parameter on the /sets and /cards endpoints.
    """
    id: Optional[str] = None
    name: Optional[str] = None
    game_value_usd: Optional[float] = None   # total estimated value of all tracked cards
    sealed_count: Optional[int] = None       # sealed products tracked for this game
