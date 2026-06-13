from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DtoPokemonTcgSet:
    """A TCG expansion set as returned by ``GET /v2/sets``.

    Field names match the Pokemon TCG API JSON exactly (camelCase) so the
    framework deserializer can map them directly — do not "pythonise" them.
    """
    id: Optional[str] = None                   # e.g. 'sv3pt5'
    name: Optional[str] = None                 # e.g. '151'
    series: Optional[str] = None               # e.g. 'Scarlet & Violet'
    printedTotal: Optional[int] = None         # cards in the printed set number
    total: Optional[int] = None                # including secret rares
    ptcgoCode: Optional[str] = None            # e.g. 'MEW'
    releaseDate: Optional[str] = None          # 'YYYY/MM/DD'
    updatedAt: Optional[str] = None
    legalities: Optional[Dict[str, Any]] = None
    images: Optional[Dict[str, Any]] = None    # {symbol, logo}
