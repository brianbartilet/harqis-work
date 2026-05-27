from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoJusttcgSet:
    """A card set within a game. Returned by ``GET /sets``.

    The ``id`` is a stable lowercase-hyphenated slug (it includes the game name
    to avoid collisions) usable as the ``set`` query parameter on /cards.
    """
    id: Optional[str] = None
    name: Optional[str] = None
    game: Optional[str] = None
    release_date: Optional[str] = None        # ISO 8601
    set_value_usd: Optional[float] = None      # total estimated value of every card in the set
    variants_count: Optional[int] = None       # distinct variants tracked in the set
    sealed_count: Optional[int] = None         # sealed products tracked for this set
