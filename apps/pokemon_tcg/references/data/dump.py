"""Offline reader for the PokemonTCG/pokemon-tcg-data JSON dump.

The upstream dump has changed layout a few times; this reader accepts the
common shapes used by the official repository:

- ``cards/en/<set-id>.json`` containing a list of card objects
- ``cards/en.json`` containing all card objects
- ``sets/en.json`` containing a list/dict of set objects

It intentionally mirrors the live API DTOs so workflow code can fall back from
``ApiServicePokemonTcgCards`` without a second projection path.
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from apps.pokemon_tcg.references.dto.card import DtoPokemonTcgCard


class PokemonTcgDataDump:
    """Read local Pokemon TCG JSON dump files when configured."""

    def __init__(self, dump_path: Optional[str]):
        self.root = Path(dump_path).expanduser() if dump_path else None

    def is_available(self) -> bool:
        return bool(self.root and self.root.exists() and self.root.is_dir())

    def load_sets(self) -> dict:
        """Return set metadata keyed by set id.

        Missing set metadata is not fatal for card lookup; cards usually embed
        their set object already. This method is mainly for smoke tests and
        diagnostics.
        """
        if not self.is_available():
            return {}
        assert self.root is not None
        candidates = [
            self.root / "sets" / "en.json",
            self.root / "sets.json",
            self.root / "sets" / "sets.json",
        ]
        for path in candidates:
            if path.is_file():
                data = self._read_json(path)
                if isinstance(data, dict) and "data" in data:
                    data = data["data"]
                if isinstance(data, dict):
                    return data
                if isinstance(data, list):
                    return {str(item.get("id")): item for item in data if isinstance(item, dict) and item.get("id")}
        # Some dump clones only have per-set card JSON. Derive minimal set map.
        sets = {}
        for card in self.iter_cards():
            if isinstance(card.set, dict) and card.set.get("id"):
                sets[str(card.set["id"])] = card.set
        return sets

    def iter_cards(self) -> Iterable[DtoPokemonTcgCard]:
        """Yield cards as ``DtoPokemonTcgCard`` instances."""
        if not self.is_available():
            return
        known = {f.name for f in fields(DtoPokemonTcgCard)}
        for path in self._card_files():
            data = self._read_json(path)
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            if isinstance(data, dict):
                data = list(data.values())
            if not isinstance(data, list):
                continue
            for raw in data:
                if isinstance(raw, dict):
                    yield DtoPokemonTcgCard(**{k: v for k, v in raw.items() if k in known})

    def find_cards(self, dex_number: int, rarities: Optional[Sequence[str]] = None) -> List[DtoPokemonTcgCard]:
        """Find cards by National Pokedex number and optional rarity list.

        Returns newest-set-first, matching the live API helper contract.
        """
        wanted = {r.lower() for r in rarities or []}
        cards = []
        for card in self.iter_cards():
            if dex_number not in (card.nationalPokedexNumbers or []):
                continue
            if wanted and (card.rarity or "").lower() not in wanted:
                continue
            cards.append(card)
        return sorted(cards, key=lambda c: c.release_date() or "", reverse=True)

    def _card_files(self) -> List[Path]:
        assert self.root is not None
        candidates: List[Path] = []
        for path in [self.root / "cards" / "en.json", self.root / "cards.json"]:
            if path.is_file():
                candidates.append(path)
        for directory in [self.root / "cards" / "en", self.root / "cards"]:
            if directory.is_dir():
                candidates.extend(sorted(directory.glob("*.json")))
        # De-dupe while preserving order.
        seen = set()
        unique = []
        for path in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(path)
        return unique

    @staticmethod
    def _read_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))
