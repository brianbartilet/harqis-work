import os, re, time, json
from datetime import datetime
from typing import Optional

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


def load_scryfall_bulk_data(folder_path: str) -> Optional[dict]:
    """
    Scans a folder for files following the pattern:
        all-cards-YYYYMMDDHHMMSS.json
    Finds the most recent (largest timestamp) and loads it as JSON.

    Args:
        folder_path (str): Path to the directory containing the JSON dump files.

    Returns:
        dict | None: JSON content from the most recent file, or None if none exist.
    """

    def build_card_index(_cards: list) -> dict:
        return {c["id"]: c for c in _cards if "id" in c}

    timestamp_pattern = re.compile(r"all-cards-(\d{14})\.json$")
    candidates = []

    for filename in os.listdir(folder_path):
        match = timestamp_pattern.search(filename)
        if match:
            timestamp_str = match.group(1)

            # Validate / parse timestamp
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S")
            except ValueError:
                continue  # skip malformed timestamps

            full_path = os.path.join(folder_path, filename)
            candidates.append((timestamp, full_path))

    if not candidates:
        return None  # no matching files found

    # Sort by newest timestamp
    candidates.sort(key=lambda x: x[0], reverse=True)
    latest_file = candidates[0][1]

    with open(latest_file, "r", encoding="utf-8") as f:
        raw =  json.load(f)
        cards = build_card_index(raw)
        return cards
