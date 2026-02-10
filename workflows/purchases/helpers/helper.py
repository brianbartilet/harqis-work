import os, re, time, ijson
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from core.utilities.logging.custom_logger import logger as log
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards


def get_scryfall_card_metadata(api_service__scryfall_cards: ApiServiceScryfallCards, guid: str, card_name: str,
                               scryfall_max_retries: int = 10):
    """ Helper function to get scryfall card metadata with retries. """
    scryfall_card = None
    for attempt in range(1, scryfall_max_retries + 1):
        try:
            scryfall_card = api_service__scryfall_cards.get_card_metadata(guid, rate_limit_delay=5)
        except Exception:
            scryfall_card = None
            if attempt == scryfall_max_retries:
                log.warn("Stopped after {0} attempts for {1}".format(scryfall_max_retries, card_name))
            time.sleep(10)

            log.warn("Retrying attempt {0}".format(attempt))

    return scryfall_card


def load_scryfall_bulk_data(folder_path: str) -> Optional[Dict[str, Any]]:
    """
    Scans `folder_path` for files matching:
        all-cards-YYYYMMDDHHMMSS.json

    Loads the newest file and returns an index: { card_id: card_object }.

    Uses streaming JSON parsing (ijson) to avoid MemoryError on huge files.
    """
    folder = Path(folder_path)
    if not folder.exists():
        return None

    timestamp_pattern = re.compile(r"all-cards-(\d{14})\.json$")

    candidates: list[tuple[datetime, Path]] = []
    for p in folder.iterdir():
        if not p.is_file():
            continue

        m = timestamp_pattern.search(p.name)
        if not m:
            continue

        try:
            ts = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            continue

        candidates.append((ts, p))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    latest_file = candidates[0][1]

    # Stream parse JSON array: [ {...}, {...}, ... ]
    cards: Dict[str, Any] = {}
    with latest_file.open("rb") as f:
        for card in ijson.items(f, "item"):
            card_id = card.get("id")
            if card_id:
                cards[card_id] = card

    return cards
