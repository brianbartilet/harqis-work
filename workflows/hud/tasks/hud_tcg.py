from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import  logger as log
from core.utilities.data.numbers import  safe_number

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_config

from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from workflows.purchases.tasks.tcg_mp_selling import load_scryfall_bulk_data

import re

_sections__tcg_mp_sections = {
    "meterLink_orders": {
        "Preset": "InjectedByTest",
    },
    "meterLink_sales": {
        "Preset": "InjectedByTest" # values must be strings
    },
    "meterLink_metrics": {
        "Preset": "InjectedByTest"# values must be strings
    }
}

def make_separator(count=100, char="="):
    """
    Creates a string separator consisting of a specified number of '=' characters."""
    s = ""
    for _ in range(count):
        s += char
    return s

@SPROUT.task()
@init_config(RAINMETER_CONFIG,
             hud_item_name='TCG ORDERS DROP',
             new_sections_dict=_sections__tcg_mp_sections,
             play_sound=True)
def show_pending_drop_off_orders(cfg_id__tcg_mp, cfg_id__scryfall, ini=ConfigHelperRainmeter()):
    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    cfg__scryfall = CONFIG_MANAGER.get(cfg_id__scryfall)

    api_service__scryfall_cards = ApiServiceScryfallCards(cfg__scryfall)
    service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    products = ApiServiceTcgMpProducts(cfg__tcg_mp)
    orders = service.get_orders()

    cards_scryfall_bulk_data = load_scryfall_bulk_data(
        api_service__scryfall_cards.config.app_data['path_folder_static_file'])


    collection_url = 'https://www.echomtg.com/apps/collection/'


    ini['meterLink']['text'] = "Collection"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(collection_url)
    ini['meterLink']['tooltiptext'] = collection_url
    ini['meterLink']['W'] = '100'

    #  region Section: meterLink_orders
    orders_url = 'https://thetcgmarketplace.com/order-history'
    ini['meterLink_orders']['Meter'] = 'String'
    ini['meterLink_orders']['MeterStyle'] = 'sItemLink'
    ini['meterLink_orders']['X'] = '(74*#Scale#)'
    ini['meterLink_orders']['Y'] = '(38*#Scale#)'
    ini['meterLink_orders']['W'] = '80'
    ini['meterLink_orders']['H'] = '55'
    ini['meterLink_orders']['Text'] = '|Orders'
    ini['meterLink_orders']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(orders_url)
    ini['meterLink_orders']['tooltiptext'] = orders_url
    #  endregion

    #  region Section: meterLink_sales
    sales_url = 'https://thetcgmarketplace.com/sales-settlement'
    ini['meterLink_sales']['Meter'] = 'String'
    ini['meterLink_sales']['MeterStyle'] = 'sItemLink'
    ini['meterLink_sales']['X'] = '(120*#Scale#)'
    ini['meterLink_sales']['Y'] = '(38*#Scale#)'
    ini['meterLink_sales']['W'] = '60'
    ini['meterLink_sales']['H'] = '55'
    ini['meterLink_sales']['Text'] = '|Sales'
    ini['meterLink_sales']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(sales_url)
    ini['meterLink_sales']['tooltiptext'] = sales_url
    #  endregion

    width_multiplier = 2.5
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

    multiple_items_oder = []
    sorted_data_single_card_name = []
    sorted_mapping = ["W", "B", "U", "R", "G", "C", "M", "L", "X"]

    def get_color_identity(card_name: str):
        search = products.search_card(card_name.strip())
        _card = search[0]
        log.info("Extracting guid on tcg mp from image url: {0}".format(_card))
        url = _card.image
        pattern = r"\b([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\b"
        match = re.search(pattern, url)
        guid = match.group(1)
        log.info("Found GUID: {0} for card: {1}".format(guid, _card))
        scryfall_card = cards_scryfall_bulk_data[guid]
        colors = scryfall_card['color_identity']

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

        return _color_identity

    for order in orders[0].data:
        if order['first_item'] is None:
            continue

        color_identity = get_color_identity(order['first_item'])

        # crop long names
        name = (order['first_item'][:48] + '..') if len(order['first_item']) > 50 else order['first_item']

        if safe_number(order['quantity']) > 1:
            order_detail = service.get_order_detail(order['order_id'])
            if len(order_detail['items']) > 1:
                multiple_items_oder.append(order_detail)

        # store for sorting
        sorted_data_single_card_name.append({
            "color_identity": color_identity,
            "quantity": order['quantity'],
            "name": name,
            "grand_total": order['grand_total'],
            "order_id": order['order_id']
        })

    sorted_data_single_card_name.sort(key=lambda r: sorted_mapping.index(r["color_identity"]))


    total_amount = sum(safe_number(item["grand_total"]) for item in sorted_data_single_card_name)
    total_cards = sum(safe_number(item["quantity"]) for item in sorted_data_single_card_name)

    ctr_lines = 4
    dump = ((
            "{0}\n"
            "ORDERS: {1}  CARDS: {2}  AMOUNT: {3}\n"
            "{0}\n")
            .format(make_separator(70),  len(sorted_data_single_card_name), total_cards, total_amount))

    for r in sorted_data_single_card_name:
        ctr_lines += 1
        add = " {0:<2} {1:<2} {2:<50} {3:>12}\n".format(
            r["quantity"],
            r["color_identity"],
            r["name"],
            f"{r['order_id'][4:]}"
        )
        dump += add

    # append multiple orders
    for r in multiple_items_oder:
        ctr_lines += 2
        add = "{0}\n>{1} ORDER ID: {2}\n".format(make_separator(70),
                                                 make_separator(8, ">"),
                                                 r['order_id'])
        dump += add

        for item in r['items']:
            ctr_lines += 1
            add = " {0:<2} {1:<2} {2:<50}\n".format(
                item["quantity"],
                get_color_identity(item['name']),
                item["name"]
            )
            dump += add

    ini['Variables']['ItemLines'] = '{0}'.format(ctr_lines)

    return dump

