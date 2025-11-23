from random import randint
import re
import json
from datetime import datetime

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log

from apps.apps_config import CONFIG_MANAGER
from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.references.web.api.item import ApiServiceEchoMTGCardItem
from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData

from apps.echo_mtg.references.dto.notes_jnfo import DtoNotesInformation
from workflows.purchases.helpers.helper import load_scryfall_bulk_data


@SPROUT.task()
@log_result()
def task_smoke():
    """Test function to add two numbers and return the result."""
    number = randint(1, 100) + randint(1, 100)
    log.info("Running a test result {0}".format(number))
    return number

@SPROUT.task()
def download_scryfall_bulk_data(cfg_id__scryfall: str):
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)
    api_service__scryfall_cards_bulk = ApiServiceScryfallBulkData(cfg__scryfall)
    api_service__scryfall_cards_bulk.download_bulk_file()

    return


@SPROUT.task()
@log_result()
def generate_tcg_mappings(cfg_id__tcg_mp: str, cfg_id__echo_mtg: str, cfg_id__echo_mtg_fe: str, cfg_id__scryfall: str):
    """ ../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    cfg__echo_mtg_fe = CONFIG_MANAGER.get(cfg_id__echo_mtg_fe)
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)

    api_service__echo_mtg_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    api_service__echo_mtg_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
    api_service__echo_mtg_cards_fe = ApiServiceEchoMTGCardItem(cfg__echo_mtg_fe)
    api_service__tcg_mp_products = ApiServiceTcgMpProducts(cfg__tcg_mp)
    api_service__scryfall_cards = ApiServiceScryfallCards(cfg__scryfall)

    cards_echo = api_service__echo_mtg_inventory.get_collection(tradable_only=1)
    cards_scryfall_bulk_data = load_scryfall_bulk_data(
        api_service__scryfall_cards.config.app_data['path_folder_static_file'])

    for card_echo in cards_echo:
        log.info("Retrieve echo mtg card meta data.")
        card_meta = api_service__echo_mtg_cards_fe.get_card_meta(card_echo['emid'])
        card_name = card_meta['name_clean']
        card_tcg_id = card_meta['tcgplayer_id']
        log.info("Searching for card: {0}".format(card_name))
        search_results = api_service__tcg_mp_products.search_card(card_name)
        match_found = False
        guid = None
        scryfall_card = None

        log.info("Checking if notes exist and skipping if so.")
        if card_echo['note_id'] != 0:
            log.warn("Note already exists for: {0} {1}".format(card_name, card_echo['inventory_id']))
            notes_fetch = api_service__echo_mtg_notes.get_note(card_echo['note_id'])
            log.info("Showing value:\n%s", json.dumps(notes_fetch['note']['note'], indent=4))
            continue

        for item in search_results:
            log.info("Attempting to extract guid on tcg mp from image url: {0}".format(card_name))
            try:
                log.info("Extracting guid on tcg mp from image url: {0}".format(card_name))
                url = item.image
                pattern = r"\b([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\b"
                match = re.search(pattern, url)
                guid = match.group(1)
                log.info("Found GUID: {0} for card: {1}".format(guid, card_name))
            except TypeError:
                log.warn("No guid found for card skipping: {0}".format(card_name))

            log.info("Attempting to find card on scryfall: id: {0} name: {1}".format(card_tcg_id, card_name))
            try:
                scryfall_card = cards_scryfall_bulk_data[guid]
                match_found = True
                log.info("Card json:\n%s", json.dumps(scryfall_card, indent=4))
            except KeyError:
                scryfall_card = None

            if not scryfall_card:
                log.warn("Scryfall unable to get card metadata skipping {0}".format(card_name))
                continue

        if not match_found:
            log.warn("No match found for card: {0}".format(card_name))
            continue

        log.info("Creating json information as note for {0}".format(card_name))
        notes_dto = DtoNotesInformation(
            scryfall_gui=guid,
            tcgplayer_id=scryfall_card['tcgplayer_id'],
            tcg_mp_card_id=0,
            tcg_mp_listing_id=0,
            tcg_mp_selling_price=0,
            tcg_mp_smart_pricing=0,
            tcg_price=scryfall_card['prices']['usd'],
            last_updated=datetime.now().isoformat()
        )
        note_json_string = notes_dto.get_json()

        log.info("Updating note for card: {0}".format(card_name))
        api_service__echo_mtg_notes.create_note(card_echo['inventory_id'], note_json_string)

    return 0