import time
import re
import json
import psutil
from dataclasses import dataclass
from typing import Optional
from random import randint
from datetime import datetime, timezone, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log
from core.apps.es_logging.app.elasticsearch import post, get_index_data
from core.utilities.multiprocess import MultiProcessingClient
from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.desktop.helpers.feed import feed
from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.references.web.api.item import ApiServiceEchoMTGCardItem
from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.merchant import ApiServiceTcgMpMerchant
from apps.tcg_mp.references.dto.order import EnumTcgOrderStatus
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData
from apps.echo_mtg.references.dto.notes_jnfo import DtoNotesInformation

from workflows.purchases.helpers.helper import load_scryfall_bulk_data
from workflows.purchases.helpers.mp_logging import log_mp_summary


@SPROUT.task(queue='tcg')
@log_result()
def task_smoke():
    """Test function to add two numbers and return the result."""
    number = randint(1, 100) + randint(1, 100)
    log.info("Running a test result {0}".format(number))
    return number

@SPROUT.task(queue='tcg')
@feed()
def download_scryfall_bulk_data(cfg_id__scryfall: str):
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)
    api_service__scryfall_cards_bulk = ApiServiceScryfallBulkData(cfg__scryfall)
    api_service__scryfall_cards_bulk.download_bulk_file()

    return "SUCCESS"


# region task: generate_tcg_mappings, do not multiprocess because of bulk file

@SPROUT.task(queue='tcg')
@log_result()
@feed()
def generate_tcg_mappings(cfg_id__tcg_mp: str, cfg_id__echo_mtg: str, cfg_id__echo_mtg_fe: str, cfg_id__scryfall: str,
                          force_generate=False):
    """ ../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    cfg__echo_mtg_fe = CONFIG_MANAGER.get(cfg_id__echo_mtg_fe)
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)

    api_service__echo_mtg_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    api_service__echo_mtg_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
    api_service__echo_mtg_cards_fe = ApiServiceEchoMTGCardItem(cfg__echo_mtg_fe)
    api_service__tcg_mp_products = ApiServiceTcgMpProducts(cfg__tcg_mp)
    api_service__tcg_mp_merchant = ApiServiceTcgMpMerchant(cfg__tcg_mp)
    api_service__scryfall_cards = ApiServiceScryfallCards(cfg__scryfall)

    cards_echo = api_service__echo_mtg_inventory.get_collection(tradable_only=1)
    cards_scryfall_bulk_data = load_scryfall_bulk_data(
        api_service__scryfall_cards.config.app_data['path_folder_static_file'])

    # turn off listings
    if force_generate:
        api_service__tcg_mp_merchant.set_listing_status(0)

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

        if force_generate:
            log.warn("Try to delete existing note")
            try:
                api_service__echo_mtg_notes.delete_note(card_echo['note_id'])
            except Exception:
                log.exception("Error deleting existing note. Skipping...")
                continue
        else:
            log.info("Checking if notes exist and skipping if so.")
            notes_fetch = api_service__echo_mtg_notes.get_note(card_echo['note_id'])
            if (notes_fetch['status'] == 'error') and (notes_fetch['note'] == 'not found'):
                log.warn("Note already exists for: {0} {1}".format(card_name, card_echo['inventory_id']))
            else:
                continue

        tcg_mp_card_id = 0
        for item in search_results:
            log.info("Attempting to extract guid on tcg mp from image url: {0}".format(card_name))
            try:
                log.info("Extracting guid on tcg mp from image url: {0}".format(card_name))
                tcg_mp_card_id = item.id
                url = item.image
                pattern = r"\b([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\b"
                match = re.search(pattern, url or "")
                if not match:
                    log.warning("No guid found in image url. card=%s url=%s", card_name, url)
                    continue
                guid = match.group(1)
                log.info("Found GUID: {0} for card: {1}".format(guid, card_name))
            except TypeError:
                log.exception("No guid found for card skipping: {0}".format(card_name))

            log.info("Attempting to find card on scryfall: id: {0} name: {1}".format(card_tcg_id, card_name))
            try:
                scryfall_card = cards_scryfall_bulk_data[guid]
                match_found = True
            except KeyError:
                scryfall_card = None

            if not scryfall_card:
                log.warn("Scryfall unable to get card metadata skipping {0}".format(card_name))
                continue

        if not match_found:
            log.warn("No match found for card: {0}".format(card_name))
            continue

        log.info("Creating json information as note for {0}".format(card_name))
        tcg_price = 0
        tcgplayer_id = "None"
        function = generate_tcg_mappings.__name__
        error=""
        try:
            tcgplayer_id = "None" if scryfall_card is None else scryfall_card['tcgplayer_id']
            tcg_price = "None" if scryfall_card is None else scryfall_card['prices']['usd']
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        notes_dto = DtoNotesInformation(
            scryfall_gui=guid,
            tcgplayer_id=tcgplayer_id,
            tcg_mp_card_id=tcg_mp_card_id,
            tcg_mp_listing_id=0,
            tcg_mp_selling_price=0,
            tcg_mp_smart_pricing=0,
            tcg_price=tcg_price,
            last_updated=datetime.now().isoformat(),
            function=function,
            error=error
        )
        note_json_string = notes_dto.get_json()

        log.info("Create note for card: {0}".format(card_name))
        api_service__echo_mtg_notes.create_note(card_echo['inventory_id'], note_json_string)

    # enable listings
    if force_generate:
        api_service__tcg_mp_merchant.set_listing_status(1)

    return "SUCCESS"

# endregion


# region task: generate_tcg_listings

_log_worker_generate_tcg_listings = create_logger("generate_tcg_listings.worker")

def _worker_generate_tcg_listings(task: dict):
    """
    Worker executed in a separate process.
    """
    card_name = ""
    try:
        card_echo = task["card_echo"]
        cfg_id__tcg_mp = task["cfg_id__tcg_mp"]
        cfg_id__echo_mtg = task["cfg_id__echo_mtg"]
        cfg_id__echo_mtg_fe = task["cfg_id__echo_mtg_fe"]

        # --- imports inside process ---
        from apps.apps_config import CONFIG_MANAGER
        from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
        from apps.echo_mtg.references.web.api.item import ApiServiceEchoMTGCardItem
        from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish

        cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
        cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
        cfg__echo_mtg_fe = CONFIG_MANAGER.get(cfg_id__echo_mtg_fe)

        api_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
        api_cards_fe = ApiServiceEchoMTGCardItem(cfg__echo_mtg_fe)
        api_publish = ApiServiceTcgMpPublish(cfg__tcg_mp)

        card_meta = api_cards_fe.get_card_meta(card_echo["emid"])
        card_name = card_meta["name_clean"]
        try:
            note = api_notes.get_note(card_echo["note_id"])
            json_note = json.loads(note["note"]["note"])
        except Exception:
            _log_worker_generate_tcg_listings.warning(f"Skipping {card_name}: invalid note")
            return {"status": "skipped", "card": card_name}

        if json_note["tcg_mp_listing_id"] == 0:
            try:
                response = api_publish.add_listing(
                    price=card_echo["tcg_market"],
                    quantity=1,
                    foil=card_echo["foil"],
                    product_id=json_note["tcg_mp_card_id"],
                )
                tcg_mp_listing_id_create = response['insertId']
                json_note["tcg_mp_listing_id"] = tcg_mp_listing_id_create
                json_note["function"] = generate_tcg_listings.__name__
                created = True
                _log_worker_generate_tcg_listings.info(f"Created listing for {card_name}.")
            except Exception:
                _log_worker_generate_tcg_listings.exception(f"Failed to create listing for {card_name}")
                created = False
        else:
            created = False

        # add tcg listing id to echo mtg card
        time.sleep(5)
        note_json_string = json.dumps(json_note)

        log.info("Create note for card: {0}".format(card_name))
        api_notes.update_note(card_echo['note_id'], note_json_string)

        return {
            "status": "ok",
            "card": card_name,
            "created": created,
        }

    except Exception as e:
        _log_worker_generate_tcg_listings.exception("Unhandled worker error")
        return {"card": card_name, "status": "error", "error": str(e)}


@SPROUT.task(queue="tcg")
@log_result()
@feed()
def generate_tcg_listings(
    cfg_id__tcg_mp: str,
    cfg_id__echo_mtg: str,
    cfg_id__echo_mtg_fe: str,
    worker_count=4,
):
    """../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""

    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    api_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)

    cards_echo = api_inventory.get_collection(tradable_only=1) or []
    if not cards_echo:
        log.info("No tradable cards found.")
        return "SUCCESS"

    tasks = [
        {
            "card_echo": card,
            "cfg_id__tcg_mp": cfg_id__tcg_mp,
            "cfg_id__echo_mtg": cfg_id__echo_mtg,
            "cfg_id__echo_mtg_fe": cfg_id__echo_mtg_fe,
        }
        for card in cards_echo
    ]

    mp_client = MultiProcessingClient(
        tasks=tasks,
        worker_count=worker_count or min(4, psutil.cpu_count()),
    )

    mp_client.execute_tasks(_worker_generate_tcg_listings, timeout_secs=60 * 30)
    results = mp_client.get_tasks_output()
    log_mp_summary(
        results,
        title="TCG listing generation",
        log=log,
    )

    return "SUCCESS"
# endregion


# region task: update_tcg_listings

@dataclass
class PricingDecision:
    price: Optional[float] = None
    needs_lowest_seller: bool = False


def _update_pricing_calc(
    change_7_day: float,
    price: float,
    conversion_multiplier: float = 1.10,
    threshold_pct: float = 10.0,
) -> PricingDecision:
    change = float(change_7_day)

    # Rule 2: stable upward
    if 0 < change <= threshold_pct:
        return PricingDecision(price=round(price * conversion_multiplier, 2))

    # Rule 1: down / flat → need lowest seller
    if change <= 0:
        return PricingDecision(needs_lowest_seller=True)

    # Rule 3: strong upward
    extra_pct = change - threshold_pct
    final_price = price * conversion_multiplier * (1.0 + extra_pct / 100.0)
    return PricingDecision(price=round(final_price, 2))



def _worker_update_tcg_listings_prices(task: dict):
    """
    Worker executed in a separate process.
    """
    card_name = ""
    try:
        # --- unpack task ---
        card_echo = task["card_echo"]
        cfg_id__tcg_mp = task["cfg_id__tcg_mp"]
        cfg_id__echo_mtg = task["cfg_id__echo_mtg"]
        cfg_id__echo_mtg_fe = task["cfg_id__echo_mtg_fe"]

        # --- imports inside process ---
        from apps.apps_config import CONFIG_MANAGER
        from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
        from apps.echo_mtg.references.web.api.item import ApiServiceEchoMTGCardItem
        from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish
        from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts

        cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
        cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
        cfg__echo_mtg_fe = CONFIG_MANAGER.get(cfg_id__echo_mtg_fe)

        api_publish = ApiServiceTcgMpPublish(cfg__tcg_mp)
        api_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
        api_cards_fe = ApiServiceEchoMTGCardItem(cfg__echo_mtg_fe)
        api_product = ApiServiceTcgMpProducts(cfg__tcg_mp)

        # --- original logic ---
        card_meta = api_cards_fe.get_card_meta(card_echo["emid"])
        card_name = card_meta["name_clean"]
        try:
            note = api_notes.get_note(card_echo["note_id"])
            json_note = json.loads(note["note"]["note"])
            json_note["function"] = update_tcg_listings_prices.__name__
        except Exception:
            _log_worker_generate_tcg_listings.warn(f"Skipping {card_name}: invalid note")
            return {"status": "skipped", "card": card_name}

        decision = _update_pricing_calc(
            change_7_day=card_echo["price_change"],
            price=card_echo["tcg_market"]
        )
        fallback_price = round(card_echo["tcg_market"] * 1.10, 2)
        if decision.needs_lowest_seller:
            try:
                listings = api_product.search_single_card_listings(json_note["tcg_mp_card_id"], foil=card_echo['foil'])
                post_price = listings[0]['price']
            except IndexError:
                post_price = fallback_price
        else:
            post_price = decision.price
        json_note["tcg_mp_selling_price"] = post_price

        try:
            api_publish.edit_listing(
                price=post_price,
                quantity=1,
                foil=card_echo["foil"],
                listing_id=json_note["tcg_mp_listing_id"],
            )
            updated = True
        except Exception:
            _log_worker_generate_tcg_listings.exception(f"Failed to create listing for {card_name}")
            updated = False

        time.sleep(5)
        note_json_string = json.dumps(json_note)

        log.info("Create note for card: {0}".format(card_name))
        api_notes.update_note(card_echo['note_id'], note_json_string)

        return {
            "status": "ok",
            "card": card_name,
            "updated": updated,
        }

    except Exception as e:
        _log_worker_generate_tcg_listings.exception("Unhandled worker error")
        return {"card": card_name, "status": "error", "error": str(e)}


@SPROUT.task(queue="tcg")
@log_result()
@feed()
def update_tcg_listings_prices(
    cfg_id__tcg_mp: str,
    cfg_id__echo_mtg: str,
    cfg_id__echo_mtg_fe: str,
    worker_count=4,
):
    """../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""

    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    api_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)

    cards_echo = api_inventory.get_collection(tradable_only=1) or []
    if not cards_echo:
        log.info("No tradable cards found.")
        return "SUCCESS"

    tasks = [
        {
            "card_echo": card,
            "cfg_id__tcg_mp": cfg_id__tcg_mp,
            "cfg_id__echo_mtg": cfg_id__echo_mtg,
            "cfg_id__echo_mtg_fe": cfg_id__echo_mtg_fe,
        }
        for card in cards_echo
    ]

    mp_client = MultiProcessingClient(
        tasks=tasks,
        worker_count=worker_count or min(4, psutil.cpu_count()),
    )

    mp_client.execute_tasks(_worker_update_tcg_listings_prices, timeout_secs=60 * 30)
    results = mp_client.get_tasks_output()

    log_mp_summary(
        results,
        title="TCG listing price update",
        log=log,
    )

    return "SUCCESS"

# endregion


@SPROUT.task(queue='tcg')
@log_result()
@feed()
def generate_audit_for_tcg_orders(cfg_id__tcg_mp: str) -> None:
    """
    Poll TCG MP orders, compare against ES 'current' index, and
    write changes into:
      - CURRENT_INDEX: latest status per order (1 doc per external_id)
      - AUDIT_INDEX: append-only change log (1 doc per change event)
    """
    CURRENT_INDEX = "tcg-mp-audit-current"
    AUDIT_INDEX = "tcg-mp-status-audit"

    # completed orders for lasts 30 days only
    today = datetime.today().date()
    date_range_from = today - timedelta(days=15)
    date_range_to = today

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    orders_1 = service.get_orders(by_status=EnumTcgOrderStatus.PENDING_DROP_OFF)
    orders_2 = service.get_orders(by_status=EnumTcgOrderStatus.ARRIVED_BRANCH)
    orders_3 = service.get_orders(by_status=EnumTcgOrderStatus.DROPPED)
    orders_4 = service.get_orders(by_status=EnumTcgOrderStatus.COMPLETED,
                                  date_range_from=date_range_from.isoformat(),
                                  date_range_to=date_range_to.isoformat())
    orders_5 = service.get_orders(by_status=EnumTcgOrderStatus.PICKED_UP)

    orders = [
        order
        for page in [orders_1, orders_2, orders_3, orders_4, orders_5,]
        if page
        for order in (page[0].data or [])
    ]
    # ----- helpers ---------------------------------------------------------

    def now_utc_iso() -> str:
        """Return ISO-8601 UTC string with Z suffix."""
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _unique_audit_id(external_id: int | str) -> str:
        """
        Build a stable-but-unique ES _id for audit docs so we never overwrite.
        Example: audit-108792-20251211T090142664482
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        return f"audit-{external_id}-{ts}"

    def _current_doc_id(external_id: int | str) -> str:
        """
        ES _id for current-state docs. One per order.
        Example: order-108792
        """
        return f"order-{external_id}"

    def log_status_change_es(external_id, old_status, new_status, source, raw_payload):
        """
        Append-only audit log entry in external-status-audit.
        """
        doc = {
            "external_id": external_id,
            "old_status": old_status,
            "new_status": new_status,
            "changed_at": now_utc_iso(),
            "source": source,
            "raw_payload": raw_payload,
        }

        post(
            json_dump=doc,
            index_name=AUDIT_INDEX,
            # unique per change → never overwritten
            location_key=_unique_audit_id(external_id),
            use_interval_map=False,
        )

    def set_current_state(external_id, new_status, raw_payload):
        """
        Upsert a single current-state doc per order in tcg-mp-audit-current.
        """
        doc = {
            "external_id": external_id,
            "current_status": new_status,
            "last_updated_at": now_utc_iso(),
            "last_raw_payload": raw_payload,
        }

        post(
            json_dump=doc,
            index_name=CURRENT_INDEX,
            # 1 doc per order → "order-<external_id>"
            location_key=_current_doc_id(external_id),
            use_interval_map=False,
        )

    def get_current_state(external_id):
        """
        Fetch the current-state doc (if any) for a given order.
        Returns a dict or None.
        """
        query = {
            "term": {
                "external_id": external_id
            }
        }

        states = get_index_data(
            index_name=CURRENT_INDEX,
            type_hook=dict,   # get_index_data will do dict(**_source)
            query=query,
            fetch_docs=1,
        )

        if not states:
            return None
        return states[0]

    def sync_external_item_status(
        external_id: str | int,
        new_status: str,
        raw_payload,
        source: str = "poller",
    ) -> bool:
        """
        Compare ES current state vs new_status and:
          - write audit log if changed
          - update current index

        Returns True if a change was logged, False otherwise.
        """
        try:
            state = get_current_state(external_id)
        except RuntimeError:
            # network / ES error → treat as "no state", but don't crash the whole task
            state = None

        # First time seen → seed current + audit
        if state is None:
            set_current_state(external_id, new_status, raw_payload)
            log_status_change_es(
                external_id=external_id,
                old_status=None,
                new_status=new_status,
                source=source,
                raw_payload=raw_payload,
            )
            return True

        old_status = state.get("current_status")

        # No change → nothing to do
        if old_status == new_status:
            # If you want a heartbeat, you could uncomment:
            # set_current_state(external_id, new_status, raw_payload)
            return False

        # Status changed → log + update current
        log_status_change_es(
            external_id=external_id,
            old_status=old_status,
            new_status=new_status,
            source=source,
            raw_payload=raw_payload,
        )
        set_current_state(external_id, new_status, raw_payload)
        return True

    # ----- main loop over orders -------------------------------------------

    # Adjust depending on what get_orders() returns in your service.
    # If it's a simple list of order dicts, change to: `for order in orders:`
    for order in orders:
        external_id = order.get("id")          # numeric id (108792)
        order_id = order.get("order_id")       # e.g. "0000108792"

        if not external_id or not order_id:
            # skip malformed orders; or log error if you prefer
            continue

        order_detail = service.get_order_detail(order_id)
        status_value = order_detail.get("status")  # numeric status (1, 2, 3...)

        status_enum = EnumTcgOrderStatus.from_code(status_value) if status_value is not None else None
        new_status = status_enum.label if status_enum else None

        if new_status is None:
            # Could not resolve status → skip or log a warning
            continue

        # raw_payload can just be the full detail for debugging
        sync_external_item_status(
            external_id=f"{external_id}",
            new_status=new_status,
            raw_payload=order_detail,
            source="tcg_mp_poll",
        )

