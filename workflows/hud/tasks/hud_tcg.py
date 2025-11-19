from core.apps.sprout.app.celery import SPROUT

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_config

from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER


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

@SPROUT.task()
@init_config(RAINMETER_CONFIG,
             hud_item_name='TCG ORDERS DROP',
             new_sections_dict=_sections__tcg_mp_sections,
             play_sound=True)
def show_pending_drop_off_orders(cfg_id__tcg_mp, ini=ConfigHelperRainmeter()):

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)

    collection_url = 'https://www.echomtg.com/apps/collection/'

    service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    orders = service.get_orders()

    ini['Variables']['ItemLines'] = '{0}'.format(len(orders[0].data) - 2)

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
    ini['MeterDisplay']['H'] = '300'

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*187),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackground']['H'] = ''
    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*190*#Scale#)/2'.format(width_multiplier)


    dump = ''
    for order in orders[0].data:
        if order['first_item'] is None:
            continue
        name = (order['first_item'][:48] + '..') if len(order['first_item']) > 50 else order['first_item']
        dump += " {0:<3}  {1:<50} {2:>12}\n".format(order['quantity'], name, '{0}'.format(order['grand_total']))

    return dump

