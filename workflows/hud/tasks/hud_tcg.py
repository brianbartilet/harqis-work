import re

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import  logger as log
from core.utilities.data.numbers import  safe_number
from core.utilities.data.strings import  make_separator
from core.utilities.files import move_files_any, remove_files_with_patterns, sanitize_filename
from core.utilities.resources.download_file import ServiceDownloadFile

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.tcg_mp.references.web.api.cart import ApiServiceTcgMpUserViewCart
from apps.tcg_mp.references.dto.order import EnumTcgOrderStatus
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.google_apps.references.constants import ScheduleCategory

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.scryfall.config import APP_NAME as APP_NAME_SCRYFALL
from apps.tcg_mp.config import APP_NAME as APP_NAME_TCG_MP
from apps.apps_config import CONFIG_MANAGER

from workflows.purchases.helpers.helper import load_scryfall_bulk_data
from workflows.hud.tasks.sections import sections__tcg_mp_sections


@SPROUT.task(queue='hud')
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='TCG ORDERS', new_sections_dict=sections__tcg_mp_sections,
            play_sound=True,
            schedule_categories=[ScheduleCategory.PLAY, ]
)
@feed()
def show_tcg_orders(ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))

    # region Fetch and filter data
    cfg_id__tcg_mp = kwargs.get('cfg_id__tcg_mp', APP_NAME_SCRYFALL)
    cfg_id__scryfall = kwargs.get('cfg_id__scryfall', APP_NAME_TCG_MP)

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

    #  region Build link for account balance and pending sales
    account_summary = account.get_account_summary()
    balance = account_summary['current_balance']
    pending_balance = sum(safe_number(order['grand_total']) for order in all_pending)
    sales_url = 'https://thetcgmarketplace.com/sales-settlement'
    ini['meterLink_sales']['Meter'] = 'String'
    ini['meterLink_sales']['MeterStyle'] = 'sItemLink'
    ini['meterLink_sales']['X'] = '(348*#Scale#)'
    ini['meterLink_sales']['Y'] = '(38*#Scale#)'
    ini['meterLink_sales']['W'] = '250'
    ini['meterLink_sales']['H'] = '55'
    ini['meterLink_sales']['Text'] = 'Balance: {0} Pending: {1}'.format(
        f"{balance:.2f}",
        f"{pending_balance:.2f}"
    )
    ini['meterLink_sales']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(sales_url)
    ini['meterLink_sales']['tooltiptext'] = sales_url
    #  endregion

    # region Set dimensions
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
        pattern = r"\b([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\b"
        match = re.search(pattern, url)
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

    sorted_data_single_card_name.sort(key=lambda r: sorted_mapping.index(r["color_identity"]))

    total_amount = sum(safe_number(item["grand_total"]) for item in (sorted_data_single_card_name + multiple_items_oder))
    total_cards = sum(safe_number(item["quantity"]) for item in (sorted_data_single_card_name + multiple_items_oder))
    #  endregion


    ctr_lines = 0
    dump = (("{0}\n"
            "ORDERS: {1}  CARDS: {2}  AMOUNT: {3}\n"
            "{0}\n")
            .format(make_separator(88),  len(sorted_data_single_card_name + multiple_items_oder),
                    total_cards, total_amount))
    if len(orders[0].data) == 0:
        ctr_lines += 3
        dump += "No orders to drop.\n"

    for r in sorted_data_single_card_name:
        ctr_lines += 1
        foil = "F" if str(r['foil']) == "1" else "N"

        add = " {0:<2} {1:<2} {5:<2} {6:<2} {2:<60} {3:<4} {4:>7}\n".format(
            r["quantity"],
            r["color_identity"],
            r["name"],
            f"{r['order_id'][4:]}",
            f"{r['grand_total']}",
            foil,
            r["cmc"]
        )
        dump += add

    # region Process orders with multiple cards

    # append multiple orders
    for r in multiple_items_oder:
        ctr_lines += 1
        add = "{0}\n ORDER ID: {1}\n{2}\n".format(
            make_separator(88, "="),
            r['order_id'],
            make_separator(88, '-')
        )
        dump += add

        for item in r['items']:
            # crop long names
            name = (item["name"][:50] + '..') if len(item["name"]) > 50 else item["name"]

            color, cmc = get_scryfall_info(item['name'])
            foil = "F" if str(item['crd_foil']) == "1" else "N"
            ctr_lines += 1
            add = " {0:<2} {1:<2} {3:<2} {5:<2} {2:<60} {4:>14}\n".format(
                item["quantity"],
                color,
                name,
                foil,
                item['price'],
                cmc
            )
            dump += add

    # endregion

    ini['Variables']['ItemLines'] = '{0}'.format(ctr_lines + 1)

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
        download_qr_codes_to_drive(path)

    # endregion

    return dump

