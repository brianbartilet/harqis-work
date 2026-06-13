from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional

from apps.pokemon_tcg.references.dto.set import DtoPokemonTcgSet


@dataclass
class DtoPokemonTcgCard:
    """A single card as returned by ``GET /v2/cards``.

    Field names match the Pokemon TCG API JSON exactly (camelCase) so the
    framework deserializer can map them directly. Nested objects (``set``,
    ``images``, …) are kept as raw dicts because the deserializer does not
    recurse — use :meth:`set_dto` for typed set access.
    """
    # --- identity ---
    id: Optional[str] = None                                # e.g. 'sv3pt5-199'
    name: Optional[str] = None
    supertype: Optional[str] = None                         # 'Pokémon' | 'Trainer' | 'Energy'
    subtypes: Optional[List[str]] = None                    # e.g. ['ex', 'Tera']
    number: Optional[str] = None                            # collector number within the set
    rarity: Optional[str] = None                            # e.g. 'Special Illustration Rare'
    nationalPokedexNumbers: Optional[List[int]] = None

    # --- gameplay (kept for completeness, unused by the proxy pipeline) ---
    hp: Optional[str] = None
    types: Optional[List[str]] = None                       # TCG energy types
    evolvesFrom: Optional[str] = None
    evolvesTo: Optional[List[str]] = None
    abilities: Optional[List[Dict[str, Any]]] = None
    attacks: Optional[List[Dict[str, Any]]] = None
    weaknesses: Optional[List[Dict[str, Any]]] = None
    resistances: Optional[List[Dict[str, Any]]] = None
    retreatCost: Optional[List[str]] = None
    convertedRetreatCost: Optional[int] = None
    rules: Optional[List[str]] = None
    regulationMark: Optional[str] = None

    # --- presentation / metadata ---
    artist: Optional[str] = None
    flavorText: Optional[str] = None
    set: Optional[Dict[str, Any]] = None                    # nested set object
    images: Optional[Dict[str, Any]] = None                 # {small, large}
    legalities: Optional[Dict[str, Any]] = None

    def set_dto(self) -> Optional[DtoPokemonTcgSet]:
        """Return the nested ``set`` dict as a typed :class:`DtoPokemonTcgSet`."""
        if not isinstance(self.set, dict):
            return None
        known = {f.name for f in fields(DtoPokemonTcgSet)}
        return DtoPokemonTcgSet(**{k: v for k, v in self.set.items() if k in known})

    def release_date(self) -> str:
        """The set's release date ('YYYY/MM/DD'), or '' when unknown — handy
        as a sort key for newest-first ordering."""
        if isinstance(self.set, dict):
            return self.set.get('releaseDate') or ''
        return ''
