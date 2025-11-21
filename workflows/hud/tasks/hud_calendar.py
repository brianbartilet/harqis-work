from core.apps.sprout.app.celery import SPROUT
from core.utilities.data.qlist import QList

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_config

from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents, EventType
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER


_sections__account_calendar = {
    "meterLink_broker": {
        "Preset": "InjectedByTest",
    },
    "meterLink_news": {
        "Preset": "InjectedByTest" # values must be strings
    },
    "meterLink_metrics": {
        "Preset": "InjectedByTest"# values must be strings
    }
}

@SPROUT.task()
@init_config(RAINMETER_CONFIG,
             hud_item_name='CALENDAR PEEK',
             new_sections_dict=_sections__account_calendar,
             play_sound=True)
def show_calendar_information(cfg_id__gsuite, ini=ConfigHelperRainmeter()):

    cfg__gsuite= CONFIG_MANAGER.get(cfg_id__gsuite)
    service = ApiServiceGoogleCalendarEvents(cfg__gsuite)
    events_today_all_day = service.get_all_events_today(EventType.ALL_DAY)
    events_today_scheduled = service.get_all_events_today(EventType.SCHEDULED)
    events_today_now = service.get_all_events_today(EventType.NOW)


    open_trades = []
    board_url = ''

    ini['Variables']['ItemLines'] = '{0}'.format(len(open_trades) + 2)

    ini['meterLink']['text'] = "Board"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(board_url)
    ini['meterLink']['tooltiptext'] = board_url

    #  region Section: meterLink_broker
    broker_url = 'https://trade.oanda.com/'
    ini['meterLink_broker']['Meter'] = 'String'
    ini['meterLink_broker']['MeterStyle'] = 'sItemLink'
    ini['meterLink_broker']['X'] = '(40*#Scale#)'
    ini['meterLink_broker']['Y'] = '(38*#Scale#)'
    ini['meterLink_broker']['W'] = '60'
    ini['meterLink_broker']['H'] = '55'
    ini['meterLink_broker']['Text'] = '|Broker'
    ini['meterLink_broker']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(broker_url)
    ini['meterLink_broker']['tooltiptext'] = broker_url
    #  endregion

    #  region Section: meterLink_news
    news_url = 'https://www.myfxbook.com/forex-economic-calendar'
    ini['meterLink_news']['Meter'] = 'String'
    ini['meterLink_news']['MeterStyle'] = 'sItemLink'
    ini['meterLink_news']['X'] = '(82*#Scale#)'
    ini['meterLink_news']['Y'] = '(38*#Scale#)'
    ini['meterLink_news']['W'] = '55'
    ini['meterLink_news']['H'] = '14'
    ini['meterLink_news']['Text'] = '|News'
    ini['meterLink_news']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(news_url)
    ini['meterLink_news']['tooltiptext'] = news_url
    #  endregion

    #  region Section: meterlink_metrics
    url = 'http://localhost:3001/'
    ini['meterLink_metrics']['Meter'] = 'String'
    ini['meterLink_metrics']['MeterStyle'] = 'sItemLink'
    ini['meterLink_metrics']['X'] = '(112*#Scale#)'
    ini['meterLink_metrics']['Y'] = '(38*#Scale#)'
    ini['meterLink_metrics']['W'] = '55'
    ini['meterLink_metrics']['H'] = '14'
    ini['meterLink_metrics']['Text'] = '|Metrics'
    ini['meterLink_metrics']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(url)
    ini['meterLink_metrics']['tooltiptext'] = url
    #  endregion

    ini['MeterDisplay']['W'] = '180'
    ini['MeterDisplay']['H'] = '300'

    dump = '{0}  {1}  $ {2:>10}\n'.format("TOTAL:", "UPL ", "")
    for trade in open_trades:
        unrealized_profit_loss = round(float(trade['unrealizedPL']), 2)
        dump = dump + '{0}  {1}  $ {2:>10}\n'.format(str(trade['instrument']).replace('_', ''),
                                                     'SELL'if '-' in str(trade['currentUnits']) else 'BUY ',
                                                     '{0}{1}'.format('+' if '-' not in str(unrealized_profit_loss)
                                                                     else '',
                                                     str(round(unrealized_profit_loss, 2))),
                                               )

    return dump

