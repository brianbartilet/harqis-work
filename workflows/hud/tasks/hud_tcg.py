import re
import os
import psutil
from datetime import datetime
from typing import Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import  logger as log, create_logger
from core.utilities.data.numbers import  safe_number
from core.utilities.data.strings import  make_separator
from core.utilities.files import move_files_any, remove_files_with_patterns, sanitize_filename, copy_files_to_folder
from core.utilities.multiprocess import MultiProcessingClient
from core.utilities.resources.decorators import get_decorator_attrs
from core.utilities.resources.download_file import ServiceDownloadFile

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.tcg_mp.references.web.api.cart import ApiServiceTcgMpUserViewCart, ApiServiceTcgMpWantToBuyCart
from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView
from apps.tcg_mp.references.dto.order import EnumTcgOrderStatus
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.google_apps.references.constants import ScheduleCategory

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.scryfall.config import APP_NAME as APP_NAME_SCRYFALL
from apps.tcg_mp.config import APP_NAME as APP_NAME_TCG_MP
from apps.apps_config import CONFIG_MANAGER

from workflows.purchases.helpers.helper import load_scryfall_bulk_data
from workflows.purchases.helpers.constants import image_guid_pattern
from workflows.purchases.helpers.mp_logging import log_mp_summary
from workflows.hud.tasks.sections import sections__tcg_mp_sections, sections__tcg_mp_sell_cart_sections


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='TCG ORDERS', new_sections_dict=sections__tcg_mp_sections,
            play_sound=True,
            schedule_categories=[ScheduleCategory.PLAY, ]
)
@feed()
def show_tcg_orders(ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))

    # region Fetch and filter data
    cfg_id__tcg_mp = kwargs.get('cfg_id__tcg_mp', APP_NAME_TCG_MP)
    cfg_id__scryfall = kwargs.get('cfg_id__scryfall', APP_NAME_SCRYFALL)

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)

    api_service__scryfall_cards = ApiServiceScryfallCards(cfg__scryfall)
    service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    products = ApiServiceTcgMpProducts(cfg__tcg_mp)
    account = ApiServiceTcgMpUserViewCart(cfg__tcg_mp)
    orders = service.get_orders()

    cards_scryfall_bulk_data = load_scryfall_bulk_data(
        api_service__scryfall_cards.config.app_data['path_folder_static_file'])

    orders_pending_drop_off = orders
    all_pending = orders_pending_drop_off[0].data

    for status in [EnumTcgOrderStatus.ARRIVED_BRANCH, EnumTcgOrderStatus.DROPPED, EnumTcgOrderStatus.PICKED_UP]:
        fetch_orders =  service.get_orders(by_status=status)
        if len(fetch_orders) > 0:
           all_pending = all_pending + fetch_orders[0].data
        else:
            continue
    # endregion

    #  region Build links
    collection_url = 'https://www.echomtg.com/apps/collection/'
    ini['meterLink']['text'] = "ECHOMTG"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(collection_url)
    ini['meterLink']['tooltiptext'] = collection_url
    ini['meterLink']['W'] = '100'

    orders_url = 'https://thetcgmarketplace.com/order-history'
    ini['meterLink_orders']['Meter'] = 'String'
    ini['meterLink_orders']['MeterStyle'] = 'sItemLink'
    ini['meterLink_orders']['X'] = '(52*#Scale#)'
    ini['meterLink_orders']['Y'] = '(38*#Scale#)'
    ini['meterLink_orders']['W'] = '80'
    ini['meterLink_orders']['H'] = '52'
    ini['meterLink_orders']['Text'] = '|ORDERS'
    ini['meterLink_orders']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(orders_url)
    ini['meterLink_orders']['tooltiptext'] = orders_url

    audit_url = 'http://localhost:5601/app/dashboards#/view/1d4a6453-0cea-41ed-9139-bc418ec643f8?_g=(refreshInterval:(pause:!t,value:60000),time:(from:now-1M,to:now))'
    ini['meterLink_audit']['Meter'] = 'String'
    ini['meterLink_audit']['MeterStyle'] = 'sItemLink'
    ini['meterLink_audit']['X'] = '(96*#Scale#)'
    ini['meterLink_audit']['Y'] = '(38*#Scale#)'
    ini['meterLink_audit']['W'] = '80'
    ini['meterLink_audit']['H'] = '52'
    ini['meterLink_audit']['Text'] = '|AUDIT'
    ini['meterLink_audit']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(audit_url)
    ini['meterLink_audit']['tooltiptext'] = "Kibana audit"

    #  endregion

    #  region Build link screenshots folder

    path = kwargs.get("path_to_qr", cfg__tcg_mp.app_data['save_path'])
    ini['meterLink_sc']['Meter'] = 'String'
    ini['meterLink_sc']['MeterStyle'] = 'sItemLink'
    ini['meterLink_sc']['X'] = '(132*#Scale#)'
    ini['meterLink_sc']['Y'] = '(38*#Scale#)'
    ini['meterLink_sc']['W'] = '250'
    ini['meterLink_sc']['H'] = '55'
    ini['meterLink_sc']['Text'] = '|TCG_QR'
    ini['meterLink_sc']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(path)
    ini['meterLink_sc']['tooltiptext'] = path
    #  endregion

    #  region Build link for account balance and pending sales
    account_summary = account.get_account_summary()
    balance = account_summary['current_balance']
    pending_balance = sum(safe_number(order['grand_total']) for order in all_pending)
    sales_url = 'https://thetcgmarketplace.com/sales-settlement'
    ini['meterLink_sales']['Meter'] = 'String'
    ini['meterLink_sales']['MeterStyle'] = 'sItemLink'
    ini['meterLink_sales']['X'] = '(362*#Scale#)'
    ini['meterLink_sales']['Y'] = '(38*#Scale#)'
    ini['meterLink_sales']['W'] = '250'
    ini['meterLink_sales']['H'] = '55'
    ini['meterLink_sales']['Text'] = 'Balance: {0} Pending: {1}'.format(
        f"{round(float(balance), 2)}",
        f"{round(float(pending_balance), 2)}"
    )
    ini['meterLink_sales']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(sales_url)
    ini['meterLink_sales']['tooltiptext'] = sales_url
    #  endregion


    # region Set dimensions
    max_hud_lines = 16
    width_multiplier = 3

    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*187),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*190*#Scale#)/2'.format(width_multiplier)
    # endregion

    # region Process card details
    multiple_items_oder = []
    sorted_data_single_card_name = []
    sorted_mapping = ["W", "B", "U", "R", "G", "C", "M", "L", "X"]

    def get_scryfall_info(card_name: str):
        clean = re.compile(r'^(?:\s*\[[^\]]+\]\s*)?([^()]+)')
        match = clean.search(card_name)
        card_name = match.group(1).strip()

        search = products.search_card(card_name)
        _card = search[0]
        log.info("Extracting guid on tcg mp from image url: {0}".format(_card))
        url = _card.image
        match = re.search(image_guid_pattern, url)
        guid = match.group(1)

        try:
            log.info("Found GUID: {0} for card: {1}".format(guid, _card))
            scryfall_card = cards_scryfall_bulk_data[guid]
            colors = scryfall_card['color_identity']
            _cmc = scryfall_card['cmc']
            if "land" in scryfall_card["type_line"].lower():
                _color_identity = "L"
            elif len(colors) == 1:
                _color_identity =  colors[0]
            elif len(colors) == 0:
                _color_identity = 'C'
            elif len(colors) > 1:
                _color_identity = 'M'
            else:
                _color_identity = 'X'
        except KeyError:
            _color_identity = 'X'
            _cmc = 0

        return _color_identity, int(_cmc)

    # remove invalid items
    orders[0].data = [
        order for order in orders[0].data
        if order['first_item'] is not None
    ]

    for order in orders[0].data:
        color_identity, cmc = get_scryfall_info(order['first_item'])

        # crop long names
        name = (order['first_item'][:50] + '..') if len(order['first_item']) > 50 else order['first_item']

        order_detail = service.get_order_detail(order['order_id'])
        foil = order_detail['items'][0]['crd_foil']
        if safe_number(order['quantity']) > 1:
            if len(order_detail['items']) > 1:
                order_detail['quantity'] = safe_number(order['quantity'])
                order_detail['name'] = name
                multiple_items_oder.append(order_detail)
                continue

        # store for sorting
        sorted_data_single_card_name.append({
            "color_identity": color_identity,
            "quantity": order['quantity'],
            "name": name,
            "grand_total": order['grand_total'],
            "order_id": order['order_id'],
            "foil": foil,
            "cmc": cmc
        })

    total_amount = sum(safe_number(item["grand_total"]) for item in (sorted_data_single_card_name + multiple_items_oder))
    total_cards = sum(safe_number(item["quantity"]) for item in (sorted_data_single_card_name + multiple_items_oder))

    sorted_data_single_card_name.sort(
        key=lambda r: (
            sorted_mapping.index(r["color_identity"]),
            r["cmc"],
            -safe_number(r["quantity"]),
        )
    )

    #  endregion

    ctr_lines = 0
    last_color = None
    dump = (("{0}\n"
            "ORDERS: {1}  CARDS: {2}  AMOUNT: {3}\n"
            "{0}\n")
            .format(make_separator(88),  len(sorted_data_single_card_name + multiple_items_oder),
                    total_cards, round(total_amount, 2)))
    if len(orders[0].data) == 0:
        ctr_lines += 3
        dump += "No orders to drop.\n"

    for r in sorted_data_single_card_name:
        ctr_lines += 1
        color = r["color_identity"]
        if last_color is not None and color != last_color:
            dump += make_separator(88, '-') + "\n"

        foil = "F" if str(r['foil']) == "1" else "N"

        add = " {0:<2} {1:<2} {5:<2} {6:<2} {2:<60} {3:<4} {4:>7}\n".format(
            r["color_identity"],
            r["quantity"],
            r["name"],
            f"{r['order_id'][4:]}",
            f"{r['grand_total']}",
            foil,
            r["cmc"]
        )
        dump += add
        last_color = color

    # region Process orders with multiple cards

    # append multiple orders
    for r in multiple_items_oder:
        ctr_lines += 1
        add = "{0}\n ORDER ID: {1}\n".format(
            make_separator(88, "="),
            r['order_id']
        )
        dump += add

        for item in r["items"]:
            color, cmc = get_scryfall_info(item["name"])
            item["_color"] = color
            item["_cmc"] = cmc

        order_index = {c: i for i, c in enumerate(sorted_mapping)}

        r["items"].sort(
            key=lambda item: order_index.get(item["_color"], len(order_index))
        )

        for item in r['items']:
            # crop long names
            name = (item["name"][:50] + '..') if len(item["name"]) > 50 else item["name"]

            color, cmc = get_scryfall_info(item['name'])

            if last_color is not None and color != last_color:
                dump += make_separator(88, '-') + "\n"

            foil = "F" if str(item['crd_foil']) == "1" else "N"
            ctr_lines += 1
            add = " {0:<2} {1:<2} {3:<2} {5:<2} {2:<60} {4:>14}\n".format(
                color,
                item["quantity"],
                name,
                foil,
                item['price'],
                cmc
            )
            dump += add
            last_color = color

    # endregion

    dump = "[SCROLL FOR MORE]\n" + dump + "\n[END]"

    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'
    ini['Variables']['ItemLines'] = '{0}'.format(max_hud_lines)

    # region generate QR and move to remote drive force overwrite
    def download_qr_codes_to_drive(to_path: str):
        index = 0
        downloads_list = sorted_data_single_card_name + multiple_items_oder
        # start clean
        ext = "*.png"
        remove_files_with_patterns(to_path, [ext, ])
        for item in downloads_list:
            index += 1
            qr_link = service.get_order_qr_code(item['order_id'])
            download_service = ServiceDownloadFile(qr_link['qr'])
            name_write = str(item['name']).strip()
            file_name = sanitize_filename("{0}-{1}-{2}.png".format(index, item['order_id'][4:], name_write))
            download_service.download_file(file_name)
            move_files_any({file_name: to_path})

    if path := kwargs.get("path_to_qr", cfg__tcg_mp.app_data['save_path']):
        today_folder = datetime.now().strftime("%d-%m-%Y")
        dated_path = os.path.join(path, today_folder)
        # Create folder if it doesn't exist
        os.makedirs(dated_path, exist_ok=True)
        download_qr_codes_to_drive(dated_path)

        # Mirror the latest run into a stable "now" folder for quick access
        now_path = os.path.join(path, "now")
        if os.path.isdir(now_path):
            remove_files_with_patterns(now_path, ["*.png"])
        qr_files = [
            os.path.join(dated_path, f)
            for f in os.listdir(dated_path)
            if f.lower().endswith(".png")
        ]
        copy_files_to_folder(path, "now", qr_files)

    # endregion

    return {
        "text": dump,
        "summary": "{0} order(s) · {1} card(s) · ${2:.2f} · balance ${3:.2f} pending ${4:.2f}".format(
            len(sorted_data_single_card_name) + len(multiple_items_oder),
            int(safe_number(total_cards)),
            float(safe_number(total_amount)),
            float(safe_number(balance)),
            float(safe_number(pending_balance)),
        ),
        "metrics": {
            "orders": len(sorted_data_single_card_name) + len(multiple_items_oder),
            "single_card_orders": len(sorted_data_single_card_name),
            "multi_card_orders": len(multiple_items_oder),
            "total_cards": int(safe_number(total_cards)),
            "total_amount": round(float(safe_number(total_amount)), 2),
            "balance": round(float(safe_number(balance)), 2),
            "pending_balance": round(float(safe_number(pending_balance)), 2),
        },
        "links": {
            "echomtg": collection_url,
            "orders": orders_url,
            "audit": audit_url,
            "sales": sales_url,
        },
    }


# ── show_tcg_sell_cart ────────────────────────────────────────────────────────
#
# Goal: scan every one of my listings, find the first want-to-buy bid that is
# within `discount_threshold_pct` of my list price (and whose buyer-quantity
# covers my listing-quantity), queue the bid in my sell cart for manual
# fulfilment, and surface the result in the desktop HUD.
#
# Multiprocessing: one worker per listing — each worker authenticates its own
# TCG MP service, fetches the buyer bids for that listing's product+foil pair,
# applies the match rule, and (when matched) calls the want-to-buy cart
# `add` endpoint. Workers must NOT share API service objects across processes;
# every dependency is imported inside the worker function.

_log_worker_match_sell_cart = create_logger("show_tcg_sell_cart.worker")


def _is_acceptable_bid(my_price: float, bid_price: float, discount_pct: float) -> bool:
    """Return True if the buyer's bid is no more than `discount_pct` below my list.

    Example: my_price = 15.74, bid_price = 14.50, discount_pct = 10.0
        floor = 15.74 * (1 - 0.10) = 14.166
        14.50 >= 14.166 → True (acceptable — within 10% discount)
    """
    if my_price <= 0:
        return False
    floor = my_price * (1.0 - float(discount_pct) / 100.0)
    return bid_price >= floor


def _worker_match_and_add_to_sell_cart(task: dict) -> dict:
    """Worker executed in a separate process — find one acceptable buyer bid
    for this listing and queue it in the sell cart.

    Args:
        task: {
            "listing":              dict copy of DtoListingItem (cross-process safe),
            "cfg_id__tcg_mp":       config key,
            "discount_threshold_pct": float (default 10.0),
            "dry_run":              bool — when True, find a match but do NOT add.
        }

    Returns:
        Dict with status:
          - "added"           — match found AND queued in sell cart
          - "would_add"       — match found, dry_run=True
          - "no_match"        — no buyer met the price/quantity threshold
          - "no_bidders"      — buy/listed_item_filter returned []
          - "error"           — exception in worker (logged with traceback)
    """
    listing = task["listing"]
    listing_name = listing.get("name", "(unknown)")
    try:
        cfg_id__tcg_mp = task["cfg_id__tcg_mp"]
        discount_pct = float(task.get("discount_threshold_pct", 10.0))
        dry_run = bool(task.get("dry_run", False))

        # ── imports inside the process ──
        from apps.apps_config import CONFIG_MANAGER
        from apps.tcg_mp.references.web.api.buy import ApiServiceTcgMpBuy
        from apps.tcg_mp.references.web.api.cart import ApiServiceTcgMpWantToBuyCart

        cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
        api_buy = ApiServiceTcgMpBuy(cfg__tcg_mp)

        my_price = safe_number(listing.get("price"))
        my_qty = safe_number(listing.get("quantity")) or 1
        product_id = listing.get("product_id")
        foil = listing.get("crd_foil", "0")

        if not product_id:
            return {"status": "error", "card": listing_name, "error": "missing product_id"}

        bids = api_buy.get_want_to_buy_listings(product_id=product_id, foil=foil) or []
        if not bids:
            return {"status": "no_bidders", "card": listing_name, "my_price": my_price}

        # Filter: skip own listings + suspended buyers + foil mismatches +
        # bidders whose quantity won't cover the listing, then pick the first
        # bid that satisfies the price rule.
        #
        # Foil matters because /buy/listed_item_filter ignores the `foil`
        # parameter and returns BOTH foil=0 and foil=1 bids for the product.
        # Selling a non-foil card to a buyer wanting the foil (or vice versa)
        # is invalid, so we filter client-side. `crd_foil` is a string ("0"/"1")
        # on the DTO; coerce both sides to str for the comparison.
        my_foil = str(foil)
        match = None
        for bid in bids:
            bid_dict = bid.__dict__ if not isinstance(bid, dict) else bid
            if bid_dict.get("own_listing"):
                continue
            if bid_dict.get("suspended"):
                continue
            if str(bid_dict.get("crd_foil")) != my_foil:
                continue   # foil/non-foil mismatch — different physical card variant
            bid_price = safe_number(bid_dict.get("price"))
            bid_qty = safe_number(bid_dict.get("quantity")) or 0
            if bid_qty < my_qty:
                continue
            if not _is_acceptable_bid(my_price, bid_price, discount_pct):
                continue
            match = bid_dict
            break

        if not match:
            return {
                "status": "no_match",
                "card": listing_name,
                "my_price": my_price,
                "considered": len(bids),
            }

        result_common = {
            "card": listing_name,
            "my_price": my_price,
            "bid_price": safe_number(match.get("price")),
            "bid_id": match.get("id"),
            "buyer": match.get("buyer_name"),
            "foil": foil,
            "qty": my_qty,
        }

        if dry_run:
            return {"status": "would_add", **result_common}

        api_cart = ApiServiceTcgMpWantToBuyCart(cfg__tcg_mp)
        try:
            api_cart.add_to_sell_cart(listing_id=match["id"], qty=my_qty)
        except Exception as e:
            _log_worker_match_sell_cart.exception(
                "Failed to add %s to sell cart: %s", listing_name, e,
            )
            return {"status": "error", "error": str(e), **result_common}

        return {"status": "added", **result_common}

    except Exception as e:
        _log_worker_match_sell_cart.exception("Unhandled worker error for %s", listing_name)
        return {"status": "error", "card": listing_name, "error": str(e)}


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='TCG SELL CART',
            new_sections_dict=sections__tcg_mp_sell_cart_sections,
            play_sound=True,
            schedule_categories=[ScheduleCategory.PLAY, ]
)
@feed()
def show_tcg_sell_cart(ini=ConfigHelperRainmeter(),
                       worker_count: int = 4,
                       discount_threshold_pct: float = 10.0,
                       dry_run: bool = False,
                       limit: Optional[int] = None,
                       **kwargs):
    """Match my listings to want-to-buy bids and queue acceptable ones in the sell cart.

    For every entry in my TCG MP listings the worker fetches the matching
    `buy/listed_item_filter` results, takes the first bid where:

      * `bid.price >= my.price * (1 - discount_threshold_pct / 100)`
      * `bid.quantity >= my.quantity`
      * the bid is not my own listing and is not suspended

    and queues that bid in the sell cart via `want_to_buy/cart/add`. The HUD
    displays the queued items plus a link to the marketplace's sell-cart page —
    the seller fulfils the orders manually from there.

    Args:
        worker_count:           Process pool size (capped to CPU count).
        discount_threshold_pct: How much below my list price a buyer's bid is
                                allowed to be before we still accept it.
                                Default 10.0 — lower = stricter / fewer matches.
        dry_run:                When True, log/display matches but DO NOT call
                                `add_to_sell_cart`. Useful for verification.
        limit:                  Optional cap on number of listings processed
                                (handy for testing).
        cfg_id__tcg_mp:         Config key for TCG MP (default 'TCG_MP').
    """
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))

    # region Fetch my listings
    cfg_id__tcg_mp = kwargs.get('cfg_id__tcg_mp', APP_NAME_TCG_MP)
    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)

    # Always start from a clean cart so each run produces a deterministic set
    # of queued bids. Skipped under dry_run so a verification pass cannot
    # silently empty an intentional cart.
    if not dry_run:
        try:
            ApiServiceTcgMpWantToBuyCart(cfg__tcg_mp).remove_all()
            log.info("show_tcg_sell_cart: cleared sell cart before matching")
        except Exception as e:
            log.warning("show_tcg_sell_cart: cart remove_all failed (continuing): %s", e)

    api_view = ApiServiceTcgMpUserView(cfg__tcg_mp)
    listings = api_view.get_listings() or []
    if listings and limit is not None:
        listings = listings[:limit]

    # Convert dataclass DTOs to plain dicts so they cross process boundaries.
    listings_payload = []
    for item in listings:
        if hasattr(item, "__dict__"):
            listings_payload.append(dict(item.__dict__))
        elif isinstance(item, dict):
            listings_payload.append(dict(item))
    log.info("show_tcg_sell_cart: dispatching %d listing(s)", len(listings_payload))
    # endregion

    # region Multiprocess match + add
    results = []
    if listings_payload:
        tasks = [
            {
                "listing": listing,
                "cfg_id__tcg_mp": cfg_id__tcg_mp,
                "discount_threshold_pct": discount_threshold_pct,
                "dry_run": dry_run,
            }
            for listing in listings_payload
        ]
        mp_client = MultiProcessingClient(
            tasks=tasks,
            worker_count=worker_count or min(4, psutil.cpu_count()),
        )
        mp_client.execute_tasks(_worker_match_and_add_to_sell_cart, timeout_secs=60 * 60)
        results = mp_client.get_tasks_output() or []
        log_mp_summary(
            results,
            title=f"TCG sell cart matching (threshold={discount_threshold_pct}%, dry_run={dry_run})",
            log=_log_worker_match_sell_cart,
        )
    # endregion

    # region Build links
    # Use the template's default `meterLink` slot for the SELL CART label so
    # the Rainmeter HUD doesn't fall back to its placeholder text ("Link 1").
    sell_cart_url = 'https://thetcgmarketplace.com/sellcart'
    ini['meterLink']['text'] = "CART"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(sell_cart_url)
    ini['meterLink']['tooltiptext'] = sell_cart_url
    ini['meterLink']['W'] = '120'

    # DUMP — opens the dump.txt that Rainmeter writes for this HUD widget.
    # Path mirrors the pattern in hud_logs.get_schedules / hud_utils helpers:
    # <write_skin_to_path>/<skin_name>/<HUD_ITEM_NAME_NOSPACES_UPPER>/dump.txt
    meta = get_decorator_attrs(show_tcg_sell_cart, prefix='')
    hud_item = str(meta['_hud_item_name']).replace(" ", "").upper()
    dump_path = os.path.join(
        RAINMETER_CONFIG['write_skin_to_path'],
        RAINMETER_CONFIG['skin_name'],
        hud_item,
        "dump.txt",
    )
    ini['meterLink_dump']['Meter'] = 'String'
    ini['meterLink_dump']['MeterStyle'] = 'sItemLink'
    ini['meterLink_dump']['X'] = '(34*#Scale#)'
    ini['meterLink_dump']['Y'] = '(38*#Scale#)'
    ini['meterLink_dump']['W'] = '80'
    ini['meterLink_dump']['H'] = '55'
    ini['meterLink_dump']['Text'] = '|DUMP'
    ini['meterLink_dump']['LeftMouseUpAction'] = '!Execute ["{0}"]'.format(dump_path)
    ini['meterLink_dump']['tooltiptext'] = dump_path

    # Status buckets — kept for the dump header counts. The user asked to
    # keep only the SELL CART link at the top, so no separate metrics meter.
    added = [r for r in results if r.get("status") == "added"]
    would_add = [r for r in results if r.get("status") == "would_add"]
    errored = [r for r in results if r.get("status") == "error"]
    # endregion

    # region Set dimensions (mirror show_tcg_orders sizing)

    max_hud_lines = 10
    width_multiplier = 3

    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    # SkinHeight must be > Background height by ~6 px so the StrokeWidth=1
    # border on the rectangle has room to render. Using 36 here matched the
    # background exactly and the bottom edge clipped; 42 mirrors `show_tcg_orders`.
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(34+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*187),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*190*#Scale#)/2'.format(width_multiplier)
    # endregion

    # region Compose dump
    queued_amount = sum(safe_number(r.get("bid_price")) for r in (added + would_add))
    dump = (("{0}\n"
             "THRESHOLD: {1:.1f}%  CHECKED: {2}  QUEUED: {3}  AMOUNT: {4}\n"
             "{0}\n")
            .format(make_separator(88), discount_threshold_pct,
                    len(results), len(added) + len(would_add), round(queued_amount, 2)))

    queued = added + would_add
    if not queued:
        # Show a friendly "no matches" message + timestamp instead of the
        # column header. Format mirrors the user-requested output:
        #   <blank>
        #   No matching bids. Last executed on YYYY-MM-DD-HH-MM
        #   <blank><blank>
        run_ts = datetime.now().strftime("%Y-%m-%d-%H-%M")
        dump += "\nNo matching bids. Last executed on {0}\n\n".format(run_ts)
    else:
        # 88-char rows match the header/footer `make_separator(88)` exactly.
        # Layout: " F  <name 62>  <mine 7>  <bid 7>  <qty 5>"   = 88 chars
        # Numeric columns are zero-padded to 2 decimals for clean alignment.
        dump += " {0:<2} {1:<62} {2:>7} {3:>7} {4:>5}\n".format(
            "F", "Name", "Mine", "Bid", "Qty",
        )
        dump += make_separator(88, '-') + "\n"

    # Sort rows by bid price DESC so the highest-paying buyers appear first.
    # Tie-breakers: my listing price DESC, then card name (stable + readable).
    queued.sort(
        key=lambda r: (
            safe_number(r.get("bid_price")),
            safe_number(r.get("my_price")),
            r.get("card") or "",
        ),
        reverse=True,
    )
    for r in queued:
        foil = "F" if str(r.get("foil")) == "1" else "N"
        name = (r["card"][:62]) if r.get("card") and len(r["card"]) > 62 else r.get("card", "")
        qty = int(safe_number(r.get("qty")) or 1)
        dump += " {0:<2} {1:<62} {2:>7} {3:>7} {4:>5}\n".format(
            foil,
            name,
            f"{safe_number(r.get('my_price')):.2f}",
            f"{safe_number(r.get('bid_price')):.2f}",
            qty,
        )

    if errored:
        dump += "{0}\n".format(make_separator(88, '-'))
        dump += "Errors:\n"
        for r in errored:
            dump += " ! {0}: {1}\n".format(r.get("card", "(unknown)"), r.get("error", ""))

    dump = "[SCROLL FOR MORE]\n" + dump + "\n[END]"

    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'
    ini['Variables']['ItemLines'] = '{0}'.format(max_hud_lines)
    # endregion

    return {
        "text": dump,
        "summary": "checked {0} listing(s) · queued {1} · ${2:.2f} · {3} error(s) · threshold {4:.1f}%{5}".format(
            len(results),
            len(added) + len(would_add),
            float(queued_amount),
            len(errored),
            float(discount_threshold_pct),
            " (dry_run)" if dry_run else "",
        ),
        "metrics": {
            "checked": len(results),
            "added": len(added),
            "would_add": len(would_add),
            "queued": len(added) + len(would_add),
            "errored": len(errored),
            "queued_amount": round(float(queued_amount), 2),
            "discount_threshold_pct": float(discount_threshold_pct),
            "dry_run": bool(dry_run),
        },
        "links": {
            "sell_cart": sell_cart_url,
        },
    }

