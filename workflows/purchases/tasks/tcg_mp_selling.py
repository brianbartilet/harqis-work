from core.apps.sprout.app.celery import SPROUT
from core.utilities.data.qlist import QList
from core.utilities.logging.custom_logger import logger
from random import randint

from apps.apps_config import CONFIG_MANAGER

from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards


@SPROUT.task()
def add_random_numbers():
    """Test function to add two numbers and return the result."""
    return randint(1, 100) + randint(1, 100)


@SPROUT.task()
def generate_tcg_mappings(cfg_id__tcg_mp: str, cfg_id__echo_mtg: str, cfg_id__scryfall: str):
    """ ../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)

    api_service__echo_mtg_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    api_service__tcg_mp_view = ApiServiceTcgMpUserView(cfg__tcg_mp)
    api_service__tcg_mp_order = ApiServiceTcgMpOrder(cfg__tcg_mp)
    api_service__tcg_mp_products = ApiServiceTcgMpProducts(cfg__tcg_mp)
    api_service__scryfall_cards = ApiServiceScryfallCards(cfg__scryfall)

    cards_echo = api_service__echo_mtg_inventory.get_collection(tradable_only=1)
    for card in cards_echo:
        logger.info(card)



    return 0