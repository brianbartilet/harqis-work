import time
import re
import json
import os
import psutil
import requests
import random
from dataclasses import dataclass
from typing import Optional
from random import randint
from datetime import datetime, timezone, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from core.utilities.logging.custom_logger import create_logger

from core.apps.es_logging.app.elasticsearch import post, get_index_data
from core.utilities.multiprocess import MultiProcessingClient


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
from apps.echo_mtg.references.dto.notes_info import DtoNotesInformation

from workflows.purchases.helpers.helper import load_scryfall_bulk_data
from workflows.purchases.helpers.mp_logging import log_mp_summary
from workflows.purchases.helpers.constants import image_guid_pattern


tcg_mp_log = create_logger("tcg_mp_selling")

DEFAULT_CREATE_MISSING_MAPPING_NOTES = True

_TCG_MP_TRANSIENT_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
)


def _resolve_config_placeholder(value: str) -> str:
    """Resolve a literal ${VAR} left in apps_config.yaml.

    PyCharm/pytest can import apps_config before deploy.py layers machine-local
    env vars into os.environ. Celery deploys already inject those vars, but direct
    test runs need this defensive fallback for machine-scoped paths such as
    SCRY_DOWNLOADS_PATH.
    """
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\$\{([^}]+)\}", value.strip())
    if not match:
        return value

    key = match.group(1)
    resolved = os.environ.get(key)
    if resolved:
        return resolved

    try:
        from scripts.deploy import load_machine_config, machine_env_vars
        resolved = machine_env_vars(load_machine_config(None)).get(key)
    except Exception:
        resolved = None
    if resolved:
        os.environ[key] = resolved
        return resolved
    return value


def _normalize_scryfall_set(value) -> str:
    return str(value or "").strip().lower()


def _normalize_scryfall_collector_number(value) -> str:
    return str(value or "").strip().lower()


def _split_tcg_mp_card_id(card_id) -> tuple[Optional[str], Optional[str]]:
    if not card_id:
        return None, None
    parts = str(card_id).strip().split("_", 1)
    if len(parts) != 2:
        return None, None
    card_set = _normalize_scryfall_set(parts[0])
    collector_number = _normalize_scryfall_collector_number(parts[1])
    if not card_set or not collector_number:
        return None, None
    return card_set, collector_number


def _index_scryfall_cards_by_set_collector(cards_scryfall_bulk_data) -> dict[tuple[str, str], dict]:
    index = {}
    if not isinstance(cards_scryfall_bulk_data, dict):
        return index

    for card in cards_scryfall_bulk_data.values():
        if not isinstance(card, dict):
            continue
        card_set = _normalize_scryfall_set(card.get("set"))
        collector_number = _normalize_scryfall_collector_number(card.get("collector_number"))
        if not card_set or not collector_number:
            continue
        key = (card_set, collector_number)
        existing = index.get(key)
        if existing is None or (
                str(existing.get("lang") or "").lower() != "en"
                and str(card.get("lang") or "").lower() == "en"):
            index[key] = card

    return index


def _find_scryfall_card_by_set_collector(cards_by_set_collector: dict, card_set, collector_number) -> Optional[dict]:
    key = (
        _normalize_scryfall_set(card_set),
        _normalize_scryfall_collector_number(collector_number),
    )
    if not all(key):
        return None
    return cards_by_set_collector.get(key)


# region variant identity helpers
#
# A single TCG MP listing consolidates EVERY EchoMTG copy that shares the same
# sellable identity. Foil finish, language AND condition each map to a *distinct*
# marketplace listing, so every place that groups copies — mapping inheritance,
# the generate_tcg_listings adoption guard, and the update_tcg_listings_prices
# quantity count — must agree on what "same card" means. Grouping only on
# (emid, foil) over-counts mixed condition/language copies onto one listing (and
# silently never lists the odd ones out). These helpers are the single source of
# truth for that grouping and are unit-tested.

def _norm_foil(value) -> int:
    """Normalise EchoMTG/TCG foil flags (0/1/'0'/'1'/'foil'/'') to int 0|1.
    Mirrors workflows.purchases.tasks.sold_inventory_radar._norm_foil."""
    if value in (1, "1", True, "foil", "Foil", "FOIL"):
        return 1
    return 0


def _acquired_dt(card: dict) -> datetime:
    """Parse EchoMTG acquisition dates for sorting; malformed rows sort oldest."""
    raw = card.get("date_acquired_html") or card.get("date_acquired")
    if not raw:
        return datetime.min
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(raw), fmt)
        except ValueError:
            continue
    return datetime.min


_LANGUAGE_ALIASES = {
    "EN": "EN",
    "ENG": "EN",
    "ENGLISH": "EN",
    "JP": "JP",
    "JPN": "JP",
    "JA": "JP",
    "JAPANESE": "JP",
    "日本語": "JP",
    "KR": "KR",
    "KOR": "KR",
    "KO": "KR",
    "KOREAN": "KR",
    "한국어": "KR",
    "CN": "CN",
    "ZH": "CN",
    "ZHS": "CN",
    "ZHT": "CN",
    "CHINESE": "CN",
    "SIMPLIFIED CHINESE": "CN",
    "TRADITIONAL CHINESE": "CN",
    "SC": "CN",
    "TC": "CN",
    "FR": "FR",
    "FRE": "FR",
    "FRENCH": "FR",
    "DE": "DE",
    "GER": "DE",
    "GERMAN": "DE",
    "IT": "IT",
    "ITA": "IT",
    "ITALIAN": "IT",
    "ES": "ES",
    "SPA": "ES",
    "SPANISH": "ES",
    "PT": "PT",
    "POR": "PT",
    "PORTUGUESE": "PT",
    "RU": "RU",
    "RUS": "RU",
    "RUSSIAN": "RU",
}


def _normalize_language(value, default=None):
    raw = value if value not in (None, "") else default
    if raw in (None, ""):
        return None
    key = str(raw).strip().upper().replace("_", " ").replace("-", " ")
    return _LANGUAGE_ALIASES.get(key, key)


def _language_value(card: dict, default=None):
    return _normalize_language(card.get("language") or card.get("lang"), default)


def _condition_value(card: dict, default=None):
    value = card.get("condition") or default
    return str(value).upper() if value not in (None, "") else None


def _variant_key(card: dict, default_language: str = "EN", default_condition: str = "NM") -> tuple:
    """Strict identity tuple (emid, foil, language, condition) for grouping copies
    that come from the SAME inventory endpoint (get_collection), where fields are
    consistently present. Defaults mirror add_listing (EN / NM); ``default_language``
    folds in the per-run language override used by generate_tcg_listings."""
    return (
        str(card.get("emid")),
        _norm_foil(card.get("foil")),
        _language_value(card, default_language) or "EN",
        _condition_value(card, default_condition) or "NM",
    )


def _same_variant(a: dict, b: dict) -> bool:
    """Tolerant cross-endpoint variant match. ``foil`` is authoritative — both the
    get_collection and search_card endpoints expose it. ``language``/``lang`` and
    ``condition`` refine the match but are treated as wildcards when EITHER side
    omits them, so sparse search_card rows never collapse quantity to 0."""
    if _norm_foil(a.get("foil")) != _norm_foil(b.get("foil")):
        return False

    la, lb = _language_value(a), _language_value(b)
    if la is not None and lb is not None and la != lb:
        return False

    ca, cb = _condition_value(a), _condition_value(b)
    if ca is not None and cb is not None and ca != cb:
        return False

    return True


def _group_by_variant(cards: list, default_language: str = "EN") -> dict:
    """Group homogeneous get_collection rows by _variant_key. Returns
    {variant_key: [card, ...]} preserving input order within each group."""
    groups: dict = {}
    for card in cards:
        groups.setdefault(_variant_key(card, default_language=default_language), []).append(card)
    return groups


def _obj_value(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return default


def _listing_matches_variant(listing, *, product_id, foil, language, condition) -> bool:
    if _obj_value(listing, "product_id") != product_id:
        return False
    if _norm_foil(_obj_value(listing, "crd_foil", "foil")) != _norm_foil(foil):
        return False

    listing_language = _obj_value(listing, "crd_language", "language")
    if listing_language not in (None, "") and language not in (None, ""):
        if _normalize_language(listing_language) != _normalize_language(language):
            return False

    listing_condition = _obj_value(listing, "crd_condition", "condition")
    if listing_condition not in (None, "") and condition not in (None, ""):
        if str(listing_condition).upper() != str(condition).upper():
            return False

    return True


def _find_live_variant_listings(view_service, *, product_id, foil, language, condition) -> list:
    try:
        listings = view_service.get_listings() or []
    except Exception:
        return []
    if not isinstance(listings, list):
        return []
    return [
        listing for listing in listings
        if _listing_matches_variant(
            listing, product_id=product_id, foil=foil,
            language=language, condition=condition,
        )
    ]


def _choose_primary_listing(listings: list, preferred_listing_id=0):
    if not listings:
        return None
    preferred = int(preferred_listing_id or 0)
    for listing in listings:
        if int(_obj_value(listing, "listing_id", default=0) or 0) == preferred:
            return listing

    def rank(listing):
        quantity = int(_obj_value(listing, "quantity", default=0) or 0)
        listing_id = int(_obj_value(listing, "listing_id", default=0) or 0)
        return quantity, listing_id

    return max(listings, key=rank)


def _remove_duplicate_variant_listings(api_publish, listings: list, primary_listing_id: int) -> list[int]:
    duplicate_ids = [
        int(_obj_value(listing, "listing_id"))
        for listing in listings
        if int(_obj_value(listing, "listing_id", default=0) or 0) != int(primary_listing_id or 0)
    ]
    if duplicate_ids:
        api_publish.remove_listings(duplicate_ids)
    return duplicate_ids


def _choose_update_representative(group: list) -> dict:
    """Choose a variant representative that can supply listing metadata."""
    noted = [card for card in group if card.get("note_id")]
    return max(noted or group, key=_acquired_dt)


def _parse_listing_note_payload(note_response) -> Optional[dict]:
    """Return parsed TCG listing metadata from an EchoMTG note, or None.

    In this workflow a note is the explicit opt-in marker for marketplace listing.
    Tradable EchoMTG copies without this JSON metadata are collection copies and
    must not inflate TCG MP listing quantity.
    """
    if not isinstance(note_response, dict):
        return None
    note_field = note_response.get("note")
    raw = note_field.get("note") if isinstance(note_field, dict) else note_field
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        product_id = int(payload.get("tcg_mp_card_id") or 0)
    except (TypeError, ValueError):
        return None
    if product_id < 1:
        return None
    return payload


def _listable_variant_copies(copies: list, representative: dict, notes_service,
                             product_id=None) -> tuple[list, dict]:
    """Filter variant copies down to copies explicitly opted into TCG listing.

    Returns ``(listable_copies, notes_by_note_id)``. Notes are cached so workers
    can stamp only the copies that actually carry listing metadata.
    """
    listable = []
    notes_by_note_id = {}
    try:
        expected_product_id = int(product_id or 0)
    except (TypeError, ValueError):
        expected_product_id = 0
    for copy in copies or []:
        if not _same_variant(copy, representative):
            continue
        note_id = copy.get("note_id")
        if not note_id:
            continue
        try:
            payload = _parse_listing_note_payload(notes_service.get_note(note_id))
        except Exception:
            continue
        if not payload:
            continue
        try:
            payload_product_id = int(payload.get("tcg_mp_card_id") or 0)
        except (TypeError, ValueError):
            continue
        if expected_product_id and payload_product_id != expected_product_id:
            continue
        listable.append(copy)
        notes_by_note_id[note_id] = payload
    return listable, notes_by_note_id

PENDING_COMMITMENT_STATUSES = (
    EnumTcgOrderStatus.PENDING_DROP_OFF,
    EnumTcgOrderStatus.PENDING_PAYMENT,
)

HANDED_OFF_ORDER_STATUSES = (
    EnumTcgOrderStatus.DROPPED,
    EnumTcgOrderStatus.ARRIVED_BRANCH,
    EnumTcgOrderStatus.SHIPPED,
    EnumTcgOrderStatus.IN_TRANSIT,
    EnumTcgOrderStatus.PICKED_UP,
    EnumTcgOrderStatus.COMPLETED,
    EnumTcgOrderStatus.NOT_RECEIVED,
)

DATE_BOUNDED_COMMITMENT_STATUSES = (
    EnumTcgOrderStatus.COMPLETED,
    EnumTcgOrderStatus.NOT_RECEIVED,
)


def _int_value(value, default=0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _order_summaries(pages) -> list:
    summaries = []
    for page in pages or []:
        if not page:
            continue
        data = getattr(page, "data", None)
        if data is None and isinstance(page, dict):
            data = page.get("data")
        if isinstance(data, list):
            summaries.extend(data)
    return summaries


def _order_detail_items(order_detail: dict) -> list[dict]:
    if not isinstance(order_detail, dict):
        return []
    raw_items = order_detail.get("items")
    if not isinstance(raw_items, list):
        return []
    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        product_id = _int_value(_obj_value(item, "product_id", "crd_product_id", "productId"), None)
        if product_id is None:
            continue
        items.append({
            "product_id": product_id,
            "foil": _norm_foil(_obj_value(item, "crd_foil", "foil", default=0)),
            "qty": _int_value(_obj_value(item, "qty", "quantity", default=1), 1),
        })
    return items


def _reserved_quantities_by_product_foil(order_service, statuses=PENDING_COMMITMENT_STATUSES,
                                         last_x_days: Optional[int] = None,
                                         date_bounded_statuses=()) -> dict:
    """Quantities committed to open orders but not yet removed from EchoMTG.

    Pending Drop Off / Pending Payment cards are no longer available to list, but
    they can still be present in EchoMTG until handoff/reconcile. Subtracting
    these quantities prevents the updater from re-offering committed copies.
    """
    date_range_from = date_range_to = None
    if last_x_days is not None:
        today = datetime.today().date()
        date_range_from = (today - timedelta(days=last_x_days)).isoformat()
        date_range_to = today.isoformat()

    date_bounded = set(date_bounded_statuses or ())
    reserved: dict = {}
    for status in statuses:
        try:
            if status in date_bounded and date_range_from and date_range_to:
                pages = order_service.get_orders(
                    by_status=status,
                    date_range_from=date_range_from,
                    date_range_to=date_range_to,
                )
            else:
                pages = order_service.get_orders(by_status=status)
        except Exception:
            tcg_mp_log.warning("Could not fetch %s orders for reserve count", status.label)
            continue
        for summary in _order_summaries(pages):
            order_id = _obj_value(summary, "order_id")
            if not order_id:
                continue
            try:
                detail = order_service.get_order_detail(order_id)
            except Exception:
                tcg_mp_log.warning("Could not fetch order detail %s for reserve count", order_id)
                continue
            for item in _order_detail_items(detail):
                key = (item["product_id"], item["foil"])
                reserved[key] = reserved.get(key, 0) + item["qty"]
    return reserved


def _available_listing_quantity(total_quantity: int, reserved_quantities: dict,
                                product_id, foil) -> int:
    key = (_int_value(product_id, None), _norm_foil(foil))
    reserved = reserved_quantities.get(key, 0) if key[0] is not None else 0
    return max(0, int(total_quantity or 0) - int(reserved or 0))


def _safe_listing_quantity(total_quantity: int, pending_quantities: dict,
                           handed_off_quantities: dict, product_id, foil,
                           live_quantity=None) -> int:
    """Available quantity for listing updates.

    Pending orders are always subtracted because the card has been bought but may
    still be in EchoMTG. Dropped-or-later orders are handled as a cap: if TCG MP
    still has a live listing, never raise quantity above that live marketplace
    quantity while an unreconciled handed-off order exists. If the listing is
    already gone, subtract the handed-off quantity to avoid recreating it from a
    stale EchoMTG copy.
    """
    available = _available_listing_quantity(total_quantity, pending_quantities, product_id, foil)
    key = (_int_value(product_id, None), _norm_foil(foil))
    handed_off = handed_off_quantities.get(key, 0) if key[0] is not None else 0
    if handed_off < 1:
        return available
    if live_quantity is not None:
        return min(available, max(0, _int_value(live_quantity, 0)))
    return max(0, available - int(handed_off or 0))
# endregion


@log_result()
def task_smoke():
    """Test function to add two numbers and return the result."""
    number = randint(1, 100) + randint(1, 100)
    tcg_mp_log.info("Running a test result {0}".format(number))
    return number


@feed()
@SPROUT.task()
def download_scryfall_bulk_data(**kwargs):
    cfg_id__scryfall = kwargs.get("cfg_id__scryfall", "SCRYFALL")
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)
    api_service__scryfall_cards_bulk = ApiServiceScryfallBulkData(cfg__scryfall)
    api_service__scryfall_cards_bulk.download_bulk_file()

    return "SUCCESS"


# region task: generate_tcg_mappings, do not multiprocess because of bulk file


@log_result()
@feed()
@SPROUT.task()
def generate_tcg_mappings(force_generate=False, limit: Optional[int] = None, **kwargs):
    """ ../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""
    cfg_id__tcg_mp = kwargs.get("cfg_id__tcg_mp", "TCG_MP")
    cfg_id__echo_mtg = kwargs.get("cfg_id__echo_mtg", "ECHO_MTG")
    cfg_id__echo_mtg_fe = kwargs.get("cfg_id__echo_mtg_fe", "ECHO_MTG_FE")
    cfg_id__scryfall = kwargs.get("cfg_id__scryfall", "SCRYFALL")
    # This job is the metadata seeding step: tradable EchoMTG cards that do not
    # yet have TCG JSON metadata should receive the note here. Downstream listing,
    # update, and radar tasks then require that valid note before they process a
    # card. Pass create_missing_notes=False only for an audit/skip pass.
    create_missing_notes = bool(kwargs.get(
        "create_missing_notes", DEFAULT_CREATE_MISSING_MAPPING_NOTES))

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    cfg__echo_mtg_fe = CONFIG_MANAGER.get(cfg_id__echo_mtg_fe)
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)

    api_service__echo_mtg_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    api_service__echo_mtg_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
    api_service__search = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    api_service__echo_mtg_cards_fe = ApiServiceEchoMTGCardItem(cfg__echo_mtg_fe)
    api_service__tcg_mp_products = ApiServiceTcgMpProducts(cfg__tcg_mp)
    api_service__tcg_mp_merchant = ApiServiceTcgMpMerchant(cfg__tcg_mp)
    api_service__scryfall_cards = ApiServiceScryfallCards(cfg__scryfall)

    cards_echo = api_service__echo_mtg_inventory.get_collection(tradable_only=1)
    # get_collection is @deserialized(List[dict], child='items'); on a malformed
    # echo response (no 'items' key) the decorator falls back to the raw Response,
    # which then blows up with a cryptic "'Response' object is not iterable" when
    # we loop below. Fail loudly with the real cause instead.
    if not isinstance(cards_echo, list):
        raise RuntimeError(
            "echo mtg get_collection did not return a list (got {0}) — the "
            "inventory response is missing 'items'; aborting mapping generation".format(
                type(cards_echo).__name__)
        )
    cards_echo = cards_echo if limit is None else cards_echo[:limit]
    scryfall_bulk_path = _resolve_config_placeholder(
        api_service__scryfall_cards.config.app_data['path_folder_static_file'])
    cards_scryfall_bulk_data = load_scryfall_bulk_data(scryfall_bulk_path)
    cards_scryfall_by_set_collector = _index_scryfall_cards_by_set_collector(cards_scryfall_bulk_data)

    # turn off listings
    if force_generate:
        api_service__tcg_mp_merchant.set_listing_status(0)

    # region multiprocess here
    for card_echo in cards_echo:
        error=""
        tcg_mp_log.info("Retrieve echo mtg card meta data.")
        try:
            card_meta = api_service__echo_mtg_cards_fe.get_card_meta(card_echo['emid'])
            card_name = card_meta['name_clean']
            card_tcg_id = card_meta['tcgplayer_id']
            tcg_mp_log.info("Searching for card: {0}".format(card_name))
            search_results = api_service__tcg_mp_products.search_card(card_name)
            match_found = False
            guid = None
            scryfall_card = None
        except Exception as e:
            tcg_mp_log.warning("Error getting metadata: {0}".format(e))
            continue

        note_id_for_update = card_echo.get("note_id") if force_generate else None
        if force_generate:
            if note_id_for_update:
                tcg_mp_log.info(
                    "Force-regenerating existing note for %s %s.",
                    card_name, card_echo['inventory_id'])
            else:
                tcg_mp_log.info(
                    "Force-regenerating missing note for %s %s.",
                    card_name, card_echo['inventory_id'])
        else:
            tcg_mp_log.info("Checking if notes exist and skipping if so.")
            note_id = card_echo.get("note_id")
            if not note_id:
                if not create_missing_notes:
                    tcg_mp_log.info(
                        "No listing metadata note for %s %s — skipping.",
                        card_name, card_echo['inventory_id'])
                    continue
                notes_fetch = {"status": "error", "note": "not found"}
            else:
                notes_fetch = api_service__echo_mtg_notes.get_note(note_id)
            # get_note returns {'status':'error','note':'not found'} when no note
            # exists (a string), or {'note': {'note': '<json>'}} when it does (a dict).
            if (notes_fetch.get('status') == 'error') and (notes_fetch.get('note') == 'not found'):
                if not create_missing_notes:
                    tcg_mp_log.info(
                        "No listing metadata note for %s %s — skipping.",
                        card_name, card_echo['inventory_id'])
                    continue
            else:
                # A note exists. Keep it only when it is valid TCG listing metadata.
                # Empty JSON/non-TCG notes are stale placeholders and must be replaced
                # by the mapping job; otherwise cards with empty notes never recover.
                existing_note = _parse_listing_note_payload(notes_fetch)
                if existing_note:
                    continue
                if not create_missing_notes:
                    tcg_mp_log.info(
                        "Note for %s %s is not valid TCG listing metadata — skipping.",
                        card_name, card_echo['inventory_id'])
                    continue
                note_id_for_update = note_id
                tcg_mp_log.info(
                    "Replacing non-TCG metadata note for %s %s.",
                    card_name, card_echo['inventory_id'])

        tcg_mp_card_id = 0
        for item in search_results:
            tcg_mp_log.info("Attempting to resolve TCG MP print id for card: {0}".format(card_name))
            try:
                tcg_mp_log.info("Retrieving TCG MP card details for card: {0}".format(card_name))
                tcg_mp_card_id = item.id

                card = api_service__tcg_mp_products.get_single_card(tcg_mp_card_id)
                tcg_mp_print_id = getattr(card, "card_id", None)
                card_set, card_collector_number = _split_tcg_mp_card_id(tcg_mp_print_id)
                if not card_set or not card_collector_number:
                    tcg_mp_log.warning(
                        "TCG MP card_id does not contain set/collector number. card=%s card_id=%s",
                        card_name, tcg_mp_print_id)
                    continue

                """
                # DEPRECATED: move to use card_id since url does not have the scryfall id and images moved as server resources
                url = item.image
                match = re.search(image_guid_pattern, url or "")
                if not match:
                    tcg_mp_log.warning("No guid found in image url. card=%s url=%s", card_name, url)
                    continue
                guid = match.group(1)
                tcg_mp_log.info("Found GUID: {0} for card: {1}".format(guid, card_name))
                """

            except Exception:
                tcg_mp_log.exception(
                    "Could not resolve TCG MP print id for card=%s product_id=%s",
                    card_name, tcg_mp_card_id)
                continue

            tcg_mp_log.info("Attempting to find card on scryfall: id: {0} name: {1}".format(card_tcg_id, card_name))
            scryfall_card = _find_scryfall_card_by_set_collector(
                cards_scryfall_by_set_collector,
                card_set,
                card_collector_number,
            )
            if not scryfall_card:
                tcg_mp_log.warning(
                    "Scryfall unable to get exact set/collector match for %s: %s/%s",
                    card_name, card_set, card_collector_number)
                continue

            guid = scryfall_card.get("id")
            scryfall_card_tcg_id = _int_value(scryfall_card.get('tcgplayer_id'), None)
            echo_tcg_id = _int_value(card_meta.get('tcgplayer_id'), None)
            if scryfall_card_tcg_id and echo_tcg_id and scryfall_card_tcg_id != echo_tcg_id:
                tcg_mp_log.warning(
                    "Scryfall set/collector match has different tcgplayer_id for %s: "
                    "scryfall=%s echo=%s set=%s collector=%s",
                    card_name, scryfall_card_tcg_id, echo_tcg_id, card_set, card_collector_number)
                continue

            match_found = True
            break

        if not match_found:
            tcg_mp_log.warning("No match found for card: {0}".format(card_name))
            continue

        if not guid:
            # Defensive: a matched card should always carry a Scryfall GUID, but
            # never persist a note with scryfall_guid=None — it breaks later lookups.
            tcg_mp_log.warning("No scryfall guid resolved for %s — skipping note.", card_name)
            continue

        tcg_mp_log.info("Creating json information as note for {0}".format(card_name))
        tcg_price = 0
        tcgplayer_id = "None"
        function = generate_tcg_mappings.__name__
        try:
            tcgplayer_id = "None" if scryfall_card is None else scryfall_card['tcgplayer_id']
            tcg_price = "None" if scryfall_card is None else scryfall_card['prices']['usd']
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

        # Consolidate duplicate copies onto ONE marketplace listing: if another copy
        # of the SAME variant (emid+foil+language+condition) already carries a
        # listing id, inherit it so generate_tcg_listings won't create a second
        # listing for the same card. Variant-aware (not just foil) and order-robust:
        # we scan every sibling, most-recent first, instead of the old drop-newest
        # heuristic that broke when the processed card was not the newest copy.
        tcg_mp_listing_id = 0
        if not force_generate:
            try:
                existing = api_service__search.search_card(card_echo["emid"], tradable_only=1) or []
            except Exception:
                tcg_mp_log.warning("Could not search existing copies for: {0}".format(card_name))
                existing = []
            siblings = [
                c for c in existing
                if c.get("inventory_id") != card_echo.get("inventory_id")
                and _same_variant(c, card_echo)
            ]
            siblings.sort(key=_acquired_dt, reverse=True)
            for sibling in siblings:
                try:
                    note = api_service__echo_mtg_notes.get_note(sibling["note_id"])
                    sibling_note = json.loads(note["note"]["note"])
                except Exception:
                    tcg_mp_log.warning("No existing listing found for card: {0}".format(card_name))
                    continue
                if sibling_note.get("tcg_mp_listing_id", 0) > 0:
                    tcg_mp_listing_id = sibling_note["tcg_mp_listing_id"]
                    break


        notes_dto = DtoNotesInformation(
            scryfall_guid=guid,
            tcgplayer_id=tcgplayer_id,
            tcg_mp_card_id=tcg_mp_card_id,
            tcg_mp_listing_id=tcg_mp_listing_id,
            tcg_mp_selling_price=0,
            tcg_mp_smart_pricing=0,
            tcg_price=tcg_price,
            last_updated=datetime.now().isoformat(),
            function=function,
            error=error
        )
        note_json_string = notes_dto.get_json()

        try:
            if note_id_for_update:
                tcg_mp_log.info("Update note for card: {0}".format(card_name))
                try:
                    api_service__echo_mtg_notes.update_note(note_id_for_update, note_json_string)
                except Exception:
                    tcg_mp_log.warning(
                        "Error updating note %s for %s; trying create.",
                        note_id_for_update, card_name)
                    api_service__echo_mtg_notes.create_note(card_echo['inventory_id'], note_json_string)
            else:
                tcg_mp_log.info("Create note for card: {0}".format(card_name))
                api_service__echo_mtg_notes.create_note(card_echo['inventory_id'], note_json_string)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            tcg_mp_log.warning("Error creating note: {0}".format(error))
            continue

    # endregion

    # Re-enable listings if we turned them off at the start (force_generate path).
    # Without this a standalone force run leaves the store disabled until the next
    # update_tcg_listings_prices run flips it back on.
    if force_generate:
        api_service__tcg_mp_merchant.set_listing_status(1)

    return "SUCCESS"

# endregion


# region task: generate_tcg_listings

_log_worker_generate_tcg_listings = create_logger("generate_tcg_listings.worker")


def _worker_generate_tcg_listings(task: dict, conversion_multiplier = (1 + 0.20 + 0.10), commission_rate = 1.05):
    """
    Worker executed in a separate process. Handles ONE variant group: all EchoMTG
    copies that share (emid, foil, language, condition) and were flagged as needing
    a listing.

    Consolidation contract (race-safe, idempotent — closes the duplicate-listing gap):
      • Re-reads the LIVE EchoMTG copies for this variant (not just the dispatched
        group) so quantity and existing-listing detection reflect current state.
      • If ANY copy already maps to a listing, ADOPT that id (and true its quantity
        up to the live copy count) instead of creating a second listing for the
        same card.
      • Otherwise CREATE exactly one listing at quantity = live copy count.
      • Stamps the resolved listing id + price into EVERY copy's note, so a
        half-mapped variant self-heals and the next run is a no-op.

    conversion_multiplier = currency estimated rate + tcg/ck pricing diff
    """
    card_name = ""
    try:
        cards = task["cards"]
        rep = cards[0]
        cfg_id__tcg_mp = task["cfg_id__tcg_mp"]
        cfg_id__echo_mtg = task["cfg_id__echo_mtg"]
        cfg_id__echo_mtg_fe = task["cfg_id__echo_mtg_fe"]
        default_language = task.get("language") or "EN"

        # --- imports inside process ---
        from apps.apps_config import CONFIG_MANAGER
        from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
        from apps.echo_mtg.references.web.api.item import ApiServiceEchoMTGCardItem
        from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
        from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish
        from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView

        cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
        cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
        cfg__echo_mtg_fe = CONFIG_MANAGER.get(cfg_id__echo_mtg_fe)

        api_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
        api_cards_fe = ApiServiceEchoMTGCardItem(cfg__echo_mtg_fe)
        api_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)
        api_publish = ApiServiceTcgMpPublish(cfg__tcg_mp)
        api_view = ApiServiceTcgMpUserView(cfg__tcg_mp)

        time.sleep(1)
        card_meta = api_cards_fe.get_card_meta(rep["emid"])
        try:
            card_name = card_meta["name_clean"]
            rep_note = json.loads(api_notes.get_note(rep["note_id"])["note"]["note"])
        except Exception:
            _log_worker_generate_tcg_listings.warning(f"Skipping {card_name}: invalid note")
            return {"status": "skipped", "card": card_name}

        product_id = rep_note.get("tcg_mp_card_id", 0)
        if not product_id:
            _log_worker_generate_tcg_listings.warning(f"Skipping {card_name}: no tcg_mp_card_id mapping")
            return {"status": "skipped", "card": card_name}

        language = _language_value(rep, default_language) or "EN"
        condition = _condition_value(rep, "NM") or "NM"

        # Live listable copies of this exact variant — the source of truth for
        # quantity and for adopting an already-created listing. A valid JSON note
        # is the operator's explicit marketplace opt-in; note-less collection
        # copies must not inflate the listing.
        try:
            live = api_inventory.search_card(rep["emid"], tradable_only=1) or []
        except Exception:
            live = []
        if not isinstance(live, list):
            live = []
        variant_copies, note_cache = _listable_variant_copies(live, rep, api_notes, product_id)
        if not variant_copies:
            variant_copies = cards
            note_cache = {}
        total_quantity = len(variant_copies)

        # Price from the representative card's meta.
        base_price = card_meta['foil_price'] if rep['foil'] else card_meta['tcg_mid']
        if base_price is None:
            raise Exception("No pricing found for: {0}".format(card_name))
        post_price = round(base_price * conversion_multiplier * commission_rate, 2)

        # Adopt an existing listing from ANY copy of this variant (a sibling that was
        # already listed, or a mapping-inheritance leftover), else fall back to the
        # live TCG MP listing table before creating. This closes the gap where an
        # old active duplicate exists but no current EchoMTG note points at it.
        listing_id = 0
        for c in variant_copies:
            try:
                n = note_cache.get(c.get("note_id")) or _parse_listing_note_payload(
                    api_notes.get_note(c["note_id"])
                )
            except Exception:
                continue
            if n.get("tcg_mp_listing_id", 0) > 0:
                listing_id = n["tcg_mp_listing_id"]
                break

        live_listings = _find_live_variant_listings(
            api_view, product_id=product_id, foil=rep["foil"],
            language=language, condition=condition,
        )
        primary_listing = _choose_primary_listing(live_listings, listing_id)
        if primary_listing is not None:
            listing_id = int(_obj_value(primary_listing, "listing_id"))
        live_quantity = _obj_value(primary_listing, "quantity") if primary_listing is not None else None
        pending_quantities = task.get("pending_quantities") or task.get("reserved_quantities") or {}
        handed_off_quantities = task.get("handed_off_quantities") or {}
        quantity = _safe_listing_quantity(
            total_quantity, pending_quantities, handed_off_quantities,
            product_id, rep["foil"], live_quantity=live_quantity,
        )

        created = False
        duplicate_listing_ids = []
        if quantity < 1:
            if listing_id:
                api_publish.remove_listings([listing_id])
                listing_id = 0
            _log_worker_generate_tcg_listings.info(
                f"Skipped listing for {card_name}; all {total_quantity} copy/copies are committed to open orders."
            )
        elif listing_id == 0:
            response, adopted_after_timeout = _retry_add_listing(
                api_publish,
                api_view=api_view,
                max_attempts=5,
                card_name=card_name,
                price=post_price,
                quantity=quantity,
                foil=rep["foil"],
                language=language,
                condition=condition,
                product_id=product_id,
            )
            listing_id = response['insertId']
            created = not adopted_after_timeout
            if adopted_after_timeout:
                live_listings = _find_live_variant_listings(
                    api_view, product_id=product_id, foil=rep["foil"],
                    language=language, condition=condition,
                )
                duplicate_listing_ids = _remove_duplicate_variant_listings(
                    api_publish, live_listings, listing_id
                )
                _log_worker_generate_tcg_listings.info(
                    f"Adopted listing {listing_id} for {card_name} x{quantity} after add timeout; "
                    f"removed duplicate listing(s): {duplicate_listing_ids}.")
            else:
                _log_worker_generate_tcg_listings.info(
                    f"Created listing {listing_id} for {card_name} x{quantity}.")
        else:
            # Existing listing for this variant (race / half-mapped / live duplicate)
            # — true up its quantity instead of creating another listing.
            # post_price already includes commission_rate here (unlike the update
            # worker), so pass it through directly — do NOT re-apply commission.
            _retry_edit_listing(
                api_publish,
                max_attempts=5,
                price=post_price,
                quantity=quantity,
                foil=rep["foil"],
                language=language,
                condition=condition,
                listing_id=listing_id,
            )
            if live_listings:
                duplicate_listing_ids = _remove_duplicate_variant_listings(
                    api_publish, live_listings, listing_id
                )
            _log_worker_generate_tcg_listings.info(
                f"Adopted existing listing {listing_id} for {card_name} x{quantity}; "
                f"removed duplicate listing(s): {duplicate_listing_ids}.")

        # Stamp the resolved listing id + price into every copy's note (self-heal).
        time.sleep(1)
        notes_updated = 0
        for c in variant_copies:
            try:
                n = note_cache.get(c.get("note_id")) or _parse_listing_note_payload(
                    api_notes.get_note(c["note_id"])
                )
            except Exception:
                continue
            if not n:
                continue
            if n.get("tcg_mp_listing_id", 0) == listing_id and n.get("tcg_mp_selling_price") == post_price:
                continue
            n["tcg_mp_listing_id"] = listing_id
            n["tcg_mp_selling_price"] = post_price
            n["function"] = generate_tcg_listings.__name__
            try:
                api_notes.update_note(c["note_id"], json.dumps(n))
                notes_updated += 1
            except Exception:
                _log_worker_generate_tcg_listings.exception(
                    f"Failed to stamp note for {card_name} copy {c.get('inventory_id')}")

        return {
            "status": "ok",
            "card": card_name,
            "created": created,
            "listing_id": listing_id,
            "quantity": quantity,
            "total_quantity": locals().get("total_quantity", quantity),
            "reserved_quantity": max(0, locals().get("total_quantity", quantity) - quantity),
            "notes_updated": notes_updated,
            "duplicate_listing_ids": duplicate_listing_ids,
        }

    except Exception as e:
        _log_worker_generate_tcg_listings.exception("Unhandled worker error")
        return {"card": card_name, "status": "error", "error": str(e)}


def _worker_fetch_note_for_listing(task: dict):
    """
    Fetch a single card's note and return the card if it needs a new listing, else None.
    Runs inside a spawned process — all imports must be local.

    Qualifies when:
      - tcg_mp_listing_id == 0  → no listing yet, or reset by update_tcg_listings_prices
      - tcg_mp_card_id > 0     → TCG product mapping exists (required by add_listing)
    """
    from apps.apps_config import CONFIG_MANAGER
    from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
    card = task["card_echo"]
    cfg_id__echo_mtg = task["cfg_id__echo_mtg"]

    try:
        cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
        api_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
        note = api_notes.get_note(card["note_id"])
        json_note = _parse_listing_note_payload(note)
        if json_note and int(json_note.get("tcg_mp_listing_id") or 0) == 0:
            return card
    except Exception:
        pass
    return None


def _filter_cards_needing_listing(cards: list, cfg_id__echo_mtg: str, worker_count: int = 4) -> list:
    """
    Parallel pre-filter: fetch notes for all cards concurrently and return only those
    that need a new TCG MP listing. Order is not guaranteed (not required).

    Pre-filtering here avoids spawning a worker process per card in generate_tcg_listings
    only to have the worker immediately return {"status": "existing_listing"}.
    """
    tasks = [{"card_echo": card, "cfg_id__echo_mtg": cfg_id__echo_mtg} for card in cards]
    if worker_count == 1:
        return [card for card in (_worker_fetch_note_for_listing(task) for task in tasks) if card is not None]

    mp_client = MultiProcessingClient(tasks=tasks, worker_count=worker_count)
    mp_client.execute_tasks(_worker_fetch_note_for_listing, timeout_secs=60 * 30)
    return [card for card in mp_client.get_tasks_output() if card is not None]


@log_result()
@feed()
@SPROUT.task()
def generate_tcg_listings(worker_count=4, limit: Optional[int] = None, **kwargs):
    """../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""
    cfg_id__tcg_mp = kwargs.pop("cfg_id__tcg_mp", "TCG_MP")
    cfg_id__echo_mtg = kwargs.pop("cfg_id__echo_mtg", "ECHO_MTG")
    cfg_id__echo_mtg_fe = kwargs.pop("cfg_id__echo_mtg_fe", "ECHO_MTG_FE")
    # Default listing language for cards whose EchoMTG record has none. Pass
    # language='JP' (etc.) to list a non-English batch.
    language = kwargs.pop("language", "EN")

    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    api_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    api_merchant = ApiServiceTcgMpMerchant(cfg__tcg_mp)
    order_service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    pending_quantities = _reserved_quantities_by_product_foil(order_service)
    handed_off_quantities = _reserved_quantities_by_product_foil(
        order_service,
        statuses=HANDED_OFF_ORDER_STATUSES,
        last_x_days=kwargs.pop("handed_off_last_x_days", 60),
        date_bounded_statuses=DATE_BOUNDED_COMMITMENT_STATUSES,
    )

    cards_echo = api_inventory.get_collection(tradable_only=1) or []
    if not isinstance(cards_echo, list):
        raise RuntimeError(
            "echo mtg get_collection did not return a list (got {0})".format(
                type(cards_echo).__name__)
        )
    if not cards_echo:
        tcg_mp_log.info("No tradable cards found.")
        api_merchant.set_listing_status(1)
        return "SUCCESS"
    cards_echo = cards_echo if limit is None else cards_echo[:limit]
    cards_echo.reverse()

    cards_to_list = _filter_cards_needing_listing(cards_echo, cfg_id__echo_mtg, worker_count or min(4, psutil.cpu_count()))
    if not cards_to_list:
        tcg_mp_log.info(f"0 of {len(cards_echo)} cards need a new listing.")
        api_merchant.set_listing_status(1)
        return "SUCCESS"

    # Group the copies needing a listing by variant and dispatch ONE task per
    # variant — never per copy. This guarantees two unlisted copies of the same card
    # become one quantity-2 listing instead of racing two workers into two separate
    # quantity-1 listings (the duplicate-listing bug). The worker reconciles quantity
    # from the live copy count, so the group only needs a single representative.
    variant_groups = _group_by_variant(cards_to_list, default_language=language)
    tcg_mp_log.info(
        f"{len(cards_to_list)} of {len(cards_echo)} copies need a listing "
        f"across {len(variant_groups)} distinct variant(s)."
    )

    # api_service__tcg_mp_merchant.set_listing_status(0)

    tasks_generate = [
        {
            "cards": group,
            "cfg_id__tcg_mp": cfg_id__tcg_mp,
            "cfg_id__echo_mtg": cfg_id__echo_mtg,
            "cfg_id__echo_mtg_fe": cfg_id__echo_mtg_fe,
            "language": language,
            "pending_quantities": pending_quantities,
            "handed_off_quantities": handed_off_quantities,
        }
        for group in variant_groups.values()
    ]

    if worker_count == 1:
        results = [_worker_generate_tcg_listings(task) for task in tasks_generate]
    else:
        mp_client = MultiProcessingClient(
            tasks=tasks_generate,
            worker_count=worker_count or min(4, psutil.cpu_count()),
        )

        mp_client.execute_tasks(_worker_generate_tcg_listings, timeout_secs=60 * 120)
        results = mp_client.get_tasks_output()
    log_mp_summary(
        results,
        title="TCG listing generation",
        log=_log_worker_generate_tcg_listings,
    )
    api_merchant.set_listing_status(1)

    return "SUCCESS"

# endregion


# region task: update_tcg_listings

@dataclass
class PricingDecision:
    price: Optional[float] = None
    needs_lowest_seller: bool = False


def _update_pricing_calc(change_7_day: float, price: float, threshold_pct: float = 15.0,) -> PricingDecision:
    change = float(change_7_day)

    # Rule 1: down / flat → need lowest seller
    if change <= 0:
        return PricingDecision(needs_lowest_seller=True)

    # Rule 2: stable upward
    if 0 < change <= threshold_pct:
        return PricingDecision(price=round(price, 2))

    # Rule 3: strong upward
    extra_pct = change - threshold_pct
    final_price = price * (1 + extra_pct / 100.0)

    return PricingDecision(price=round(final_price, 2))


def _retry_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
    return delay * (0.7 + random.random() * 0.6)


def _primary_live_listing(api_view, *, product_id, foil, language, condition, preferred_listing_id=0):
    if api_view is None:
        return None
    live_listings = _find_live_variant_listings(
        api_view,
        product_id=product_id,
        foil=foil,
        language=language,
        condition=condition,
    )
    return _choose_primary_listing(live_listings, preferred_listing_id)


def _retry_add_listing(api_publish, *, api_view=None, max_attempts=5, base_delay=1.0,
                       max_delay=30.0, card_name="", **kwargs):
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = api_publish.add_listing(**kwargs)
            return response, False
        except _TCG_MP_TRANSIENT_EXCEPTIONS as e:
            primary_listing = _primary_live_listing(
                api_view,
                product_id=kwargs.get("product_id"),
                foil=kwargs.get("foil"),
                language=kwargs.get("language"),
                condition=kwargs.get("condition"),
            )
            if primary_listing is not None:
                return {"insertId": int(_obj_value(primary_listing, "listing_id"))}, True

            if attempt == max_attempts:
                raise

            delay = _retry_delay(attempt, base_delay, max_delay)
            context = f" for {card_name}" if card_name else ""
            _log_worker_generate_tcg_listings.warning(
                f"Transient add_listing error{context} on attempt {attempt}/{max_attempts}: {e}; "
                f"retrying after {delay:.1f}s.")
            time.sleep(delay)

            primary_listing = _primary_live_listing(
                api_view,
                product_id=kwargs.get("product_id"),
                foil=kwargs.get("foil"),
                language=kwargs.get("language"),
                condition=kwargs.get("condition"),
            )
            if primary_listing is not None:
                return {"insertId": int(_obj_value(primary_listing, "listing_id"))}, True
    return response, False


def _retry_edit_listing(api_publish, *, max_attempts=10, base_delay=1.0, max_delay=30.0, **kwargs):
    r = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = api_publish.edit_listing(**kwargs)
            return r
        except _TCG_MP_TRANSIENT_EXCEPTIONS:

            # exponential backoff + jitter
            delay = _retry_delay(attempt, base_delay, max_delay)

            if attempt == max_attempts:
                raise

            time.sleep(delay)
    return r


def _worker_update_tcg_listings_prices(task: dict, conversion_multiplier = (1.2 + 0), commission_rate = 1.05):
    """
    Worker executed in a separate process.
    conversion_multiplier = currency estimated rate + tcg/ck pricing diff
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
        from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView

        cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
        cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
        cfg__echo_mtg_fe = CONFIG_MANAGER.get(cfg_id__echo_mtg_fe)

        api_publish = ApiServiceTcgMpPublish(cfg__tcg_mp)
        api_view = ApiServiceTcgMpUserView(cfg__tcg_mp)
        api_notes = ApiServiceEchoMTGNotes(cfg__echo_mtg)
        api_cards_fe = ApiServiceEchoMTGCardItem(cfg__echo_mtg_fe)
        api_service__search = ApiServiceEchoMTGInventory(cfg__echo_mtg)

        # --- original logic ---
        try:
            card_meta = api_cards_fe.get_card_meta(card_echo["emid"])
            card_name = card_meta["name_clean"]
            note = api_notes.get_note(card_echo["note_id"])
            time.sleep(1)
            json_note = json.loads(note["note"]["note"])
            json_note["function"] = update_tcg_listings_prices.__name__
        except Exception:
            _log_worker_generate_tcg_listings.warning(f"Skipping {card_name}: invalid note")
            return {"status": "skipped", "card": card_name}

        if card_echo['foil']:
            base_price = card_meta['foil_price']
        else:
            base_price = card_meta['tcg_mid']

        if base_price is None:
            raise Exception("No pricing found for: {0}".format(card_name))

        decision = _update_pricing_calc(
            change_7_day=card_echo["price_change"],
            price=round(base_price, 2)
        )

        # NOTE: `needs_lowest_seller` (set for down/flat 7-day change) is NOT yet
        # implemented as an actual lowest-seller lookup — both branches price off
        # base_price. Effective behaviour today:
        #   • down/flat change → base_price * conversion_multiplier
        #   • upward change     → adjusted price (see _update_pricing_calc) * multiplier
        # Fetching the marketplace's lowest seller and undercutting is a deliberate
        # follow-up (ApiServiceTcgMpProducts.search_single_card_listings exists for it).
        if decision.needs_lowest_seller:
            post_price = round(base_price * conversion_multiplier, 2)
        else:
            post_price = round(decision.price * conversion_multiplier, 2)

        # The variant's marketplace attributes — passed to edit_listing so a JP/LP
        # listing is NOT silently flipped back to EN/NM on every price refresh (the
        # edit endpoint defaults those when omitted; the old code omitted them).
        language = _language_value(card_echo, "EN") or "EN"
        condition = _condition_value(card_echo, "NM") or "NM"
        listing_id = json_note["tcg_mp_listing_id"]

        # Quantity = live count of EchoMTG copies of the SAME variant, so duplicate
        # inventory entries consolidate into one listing rather than one listing per
        # copy. This is the single place quantity is reconciled UP; the sold-inventory
        # radar reconciles it DOWN — both off the same copy count — which is why the
        # radar MUST run first (see reconcile_then_update_tcg_listings).
        #
        # edit_listing returns '' when the listing no longer exists on TCG MP (sold or
        # removed externally). Then reset tcg_mp_listing_id to 0 so generate_tcg_listings
        # treats the card as new and recreates the listing.
        quantity = 0
        duplicate_listing_ids = []
        note_cache = {}
        try:
            time.sleep(2)
            existing = api_service__search.search_card(card_echo["emid"], tradable_only=1) or []
            matching, note_cache = _listable_variant_copies(
                existing, card_echo, api_notes, json_note.get("tcg_mp_card_id")
            )
            total_quantity = len(matching)

            live_listings = _find_live_variant_listings(
                api_view, product_id=json_note.get("tcg_mp_card_id"),
                foil=card_echo["foil"], language=language, condition=condition,
            )
            primary_listing = _choose_primary_listing(live_listings, listing_id)
            if primary_listing is not None:
                listing_id = int(_obj_value(primary_listing, "listing_id"))
            live_quantity = _obj_value(primary_listing, "quantity") if primary_listing is not None else None
            pending_quantities = task.get("pending_quantities") or task.get("reserved_quantities") or {}
            handed_off_quantities = task.get("handed_off_quantities") or {}
            quantity = _safe_listing_quantity(
                total_quantity, pending_quantities, handed_off_quantities,
                json_note.get("tcg_mp_card_id"), card_echo["foil"],
                live_quantity=live_quantity,
            )

            if quantity < 1:
                if total_quantity < 1:
                    _log_worker_generate_tcg_listings.warning(
                        f"{card_name}: no matching copies returned; leaving listing {listing_id} untouched."
                    )
                elif listing_id:
                    api_publish.remove_listings([listing_id])
                    listing_id = 0
                    _log_worker_generate_tcg_listings.info(
                        f"Removed listing for {card_name}; all {total_quantity} copy/copies are committed to open orders."
                    )
                updated = False
            else:
                edit_result = _retry_edit_listing(
                    api_publish,
                    max_attempts=10,
                    base_delay=1.0,
                    max_delay=20.0,
                    price=round(post_price * commission_rate, 2),
                    quantity=quantity,
                    foil=card_echo["foil"],
                    language=language,
                    condition=condition,
                    listing_id=listing_id,
                )

                if not edit_result:
                    _log_worker_generate_tcg_listings.warning(
                        f"Listing {listing_id} not found for {card_name}; resetting to allow recreation."
                    )
                    listing_id = 0
                    updated = False
                else:
                    if live_listings:
                        duplicate_listing_ids = _remove_duplicate_variant_listings(
                            api_publish, live_listings, listing_id
                        )
                    updated = True
        except Exception:
            _log_worker_generate_tcg_listings.exception(f"Failed to update listing for {card_name}")
            updated = False
            matching = [card_echo]

        # Stamp the (possibly reset) listing id + new price into EVERY copy's note of
        # this variant — so all copies stay consistent and a vanished listing is reset
        # across the whole variant, not just the representative.
        json_note["tcg_mp_listing_id"] = listing_id
        json_note["tcg_mp_selling_price"] = post_price
        time.sleep(2)
        siblings = matching if matching else [card_echo]
        notes_updated = 0
        for c in siblings:
            note_id = c.get("note_id", card_echo["note_id"])
            try:
                if c is card_echo:
                    payload = json_note
                else:
                    payload = note_cache.get(note_id) or _parse_listing_note_payload(
                        api_notes.get_note(note_id)
                    )
                    if not payload:
                        continue
                    payload["tcg_mp_listing_id"] = listing_id
                    payload["tcg_mp_selling_price"] = post_price
                    payload["function"] = update_tcg_listings_prices.__name__
                api_notes.update_note(note_id, json.dumps(payload))
                notes_updated += 1
            except Exception:
                _log_worker_generate_tcg_listings.exception(
                    f"Failed to stamp note for {card_name} copy {c.get('inventory_id')}")

        return {
            "status": "ok",
            "card": card_name,
            "updated": updated,
            "listing_id": listing_id,
            "quantity": quantity,
            "total_quantity": locals().get("total_quantity", quantity),
            "reserved_quantity": max(0, locals().get("total_quantity", quantity) - quantity),
            "notes_updated": notes_updated,
            "duplicate_listing_ids": duplicate_listing_ids,
        }

    except Exception as e:
        _log_worker_generate_tcg_listings.exception("Unhandled worker error")
        return {"card": card_name, "status": "error", "error": str(e)}


@log_result()
@feed()
@SPROUT.task()
def update_tcg_listings_prices(worker_count=2, limit: Optional[int] = None, **kwargs):
    """../diagrams/tcg_mp.drawio/TCGGenerate Mappings Job"""
    cfg_id__tcg_mp = kwargs.get("cfg_id__tcg_mp", "TCG_MP")
    cfg_id__echo_mtg = kwargs.get("cfg_id__echo_mtg", "ECHO_MTG")
    cfg_id__echo_mtg_fe = kwargs.get("cfg_id__echo_mtg_fe", "ECHO_MTG_FE")

    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    api_inventory = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    api_service__tcg_mp_merchant = ApiServiceTcgMpMerchant(cfg__tcg_mp)
    order_service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    pending_quantities = _reserved_quantities_by_product_foil(order_service)
    handed_off_quantities = _reserved_quantities_by_product_foil(
        order_service,
        statuses=HANDED_OFF_ORDER_STATUSES,
        last_x_days=kwargs.pop("handed_off_last_x_days", 60),
        date_bounded_statuses=DATE_BOUNDED_COMMITMENT_STATUSES,
    )

    cards_echo = api_inventory.get_collection(tradable_only=1) or []
    if not isinstance(cards_echo, list):
        raise RuntimeError(
            "echo mtg get_collection did not return a list (got {0})".format(
                type(cards_echo).__name__)
        )
    if not cards_echo:
        tcg_mp_log.info("No tradable cards found.")
        api_service__tcg_mp_merchant.set_listing_status(1)
        return "SUCCESS"

    cards_echo = cards_echo if limit is None else cards_echo[:limit]

    # Dedup to ONE task per variant. With N copies of a card the old code dispatched
    # N tasks that each recomputed the price and edited the SAME listing to the same
    # quantity — redundant API calls and N parallel writes racing on one listing. The
    # worker counts copies and stamps every sibling note, so one representative (the
    # most-recently-acquired copy) per variant fully reconciles the listing.
    # Only noted cards enter the update pipeline. The worker validates the JSON TCG
    # metadata before mutating anything, and listable quantity is counted from valid
    # metadata notes only.
    cards_echo = [card for card in cards_echo if card.get("note_id")]
    variant_groups = _group_by_variant(cards_echo)
    if not variant_groups:
        tcg_mp_log.info("No tradable cards with listing metadata notes found.")
        api_service__tcg_mp_merchant.set_listing_status(1)
        return "SUCCESS"

    # Prefer a copy with a note as the representative.
    representatives = [
        _choose_update_representative(group)
        for group in variant_groups.values()
    ]
    tcg_mp_log.info(
        f"{len(representatives)} variant listing(s) to update from {len(cards_echo)} tradable copies."
    )

    tasks_update = [
        {
            "card_echo": card,
            "cfg_id__tcg_mp": cfg_id__tcg_mp,
            "cfg_id__echo_mtg": cfg_id__echo_mtg,
            "cfg_id__echo_mtg_fe": cfg_id__echo_mtg_fe,
            "pending_quantities": pending_quantities,
            "handed_off_quantities": handed_off_quantities,
        }
        for card in representatives
    ]

    mp_client = MultiProcessingClient(
        tasks=tasks_update,
        worker_count=worker_count or min(4, psutil.cpu_count()),
    )

    mp_client.execute_tasks(_worker_update_tcg_listings_prices, timeout_secs=60 * 120)
    results = mp_client.get_tasks_output()
    api_service__tcg_mp_merchant.set_listing_status(1)
    log_mp_summary(
        results,
        title="TCG listing price update",
        log=tcg_mp_log,
    )

    return "SUCCESS"

# endregion


# region task: reconcile_then_update_tcg_listings (hard-ordered radar -> update)

@log_result()
@feed()
@SPROUT.task()
def reconcile_then_update_tcg_listings(**kwargs):
    """Hard-ordered sold-inventory reconcile -> price/quantity update.

    Replaces the previous wall-clock gap (radar 02:00, update 04:00) with an
    in-process chain so update_tcg_listings_prices can NEVER recompute listing
    quantities before radar_sold_inventory has reconciled sold-but-not-removed
    copies — the over-listing failure mode. radar runs to completion first; only
    then does update run. If radar raises, update is SKIPPED (fail-safe: better to
    leave quantities stale than to re-inflate sold cards).

    kwargs:
      radar_kwargs:  dict forwarded to radar_sold_inventory (defaults to the
                     scheduled high-confidence destructive config).
      update_kwargs: dict forwarded to update_tcg_listings_prices.
    Any ``cfg_id__*`` at the top level is merged into BOTH for convenience.
    """
    # Lazy import to avoid import-time coupling between the two task modules.
    from workflows.purchases.tasks.sold_inventory_radar import radar_sold_inventory

    cfg_passthrough = {k: v for k, v in kwargs.items() if k.startswith("cfg_id__")}
    radar_kwargs = {**cfg_passthrough, **(kwargs.get("radar_kwargs") or {})}
    update_kwargs = {**cfg_passthrough, **(kwargs.get("update_kwargs") or {})}

    tcg_mp_log.info("reconcile_then_update: running sold-inventory radar first.")
    try:
        radar_sold_inventory(**radar_kwargs)
    except Exception:
        tcg_mp_log.exception(
            "reconcile_then_update: radar FAILED; skipping price update to avoid over-listing."
        )
        return "RADAR_FAILED_UPDATE_SKIPPED"

    tcg_mp_log.info("reconcile_then_update: radar complete; running price/quantity update.")
    update_tcg_listings_prices(**update_kwargs)
    return "SUCCESS"

# endregion


@log_result()
@feed()
@SPROUT.task()
def generate_audit_for_tcg_orders(last_x_days=15, **kwargs) -> None:
    """
    Poll TCG MP orders, compare against ES 'current' index, and
    write changes into:
      - CURRENT_INDEX: latest status per order (1 doc per external_id)
      - AUDIT_INDEX: append-only change log (1 doc per change event)
    """
    CURRENT_INDEX = "tcg-mp-audit-current"
    AUDIT_INDEX = "tcg-mp-status-audit"

    # completed orders for lasts X days only
    today = datetime.today().date()
    date_range_from = today - timedelta(days=last_x_days)
    date_range_to = today

    cfg_id__tcg_mp = kwargs.get("cfg_id__tcg_mp", "TCG_MP")
    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    orders_1 = service.get_orders(by_status=EnumTcgOrderStatus.PENDING_DROP_OFF)
    orders_2 = service.get_orders(by_status=EnumTcgOrderStatus.ARRIVED_BRANCH)
    orders_3 = service.get_orders(by_status=EnumTcgOrderStatus.DROPPED)
    orders_4 = service.get_orders(by_status=EnumTcgOrderStatus.COMPLETED,
                                  date_range_from=date_range_from.isoformat(),
                                  date_range_to=date_range_to.isoformat())
    orders_5 = service.get_orders(by_status=EnumTcgOrderStatus.PICKED_UP)
    # In-transit-to-buyer state — also a "left my hands" status the sold-inventory
    # radar treats as sold. Transient + low-volume like ARRIVED_BRANCH/DROPPED, so
    # left unbounded.
    orders_8 = service.get_orders(by_status=EnumTcgOrderStatus.SHIPPED)
    orders_9 = service.get_orders(by_status=EnumTcgOrderStatus.IN_TRANSIT)
    # Terminal "left my hands" states the sold-inventory radar relies on. These
    # were previously not audited, so cancelled/not-received orders never landed
    # in tcg-mp-audit-current — date-bounded like COMPLETED to keep the poll cheap.
    orders_6 = service.get_orders(by_status=EnumTcgOrderStatus.CANCELLED,
                                  date_range_from=date_range_from.isoformat(),
                                  date_range_to=date_range_to.isoformat())
    orders_7 = service.get_orders(by_status=EnumTcgOrderStatus.NOT_RECEIVED,
                                  date_range_from=date_range_from.isoformat(),
                                  date_range_to=date_range_to.isoformat())

    orders = [
        order
        for pages in [orders_1, orders_2, orders_3, orders_4, orders_5, orders_6, orders_7, orders_8, orders_9]
        for order in _order_summaries(pages)
    ]

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

