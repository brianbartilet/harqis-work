from core.apps.sprout.app.celery import SPROUT
from core.utilities.data.qlist import QList
from core.utilities.logging.custom_logger import logger as log

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter

from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.open_trades import ApiServiceTrades
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.dto.constants import ScheduleCategory

_sections__oanda = {
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
@init_meter(RAINMETER_CONFIG,
            hud_item_name='OANDA ACCOUNT',
            new_sections_dict=_sections__oanda,
            play_sound=True,
            schedule_categories=[ScheduleCategory.FINANCE, ]
            )
def show_account_information(cfg_id__oanda, ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))

    # region Fetch OANDA data
    cfg__oanda = CONFIG_MANAGER.get(cfg_id__oanda)

    board_url = "https://trello.com/b/351MWTYe/daily-dashboard-trading"

    service = ApiServiceOandaAccount(cfg__oanda)
    response = service.get_account_info()

    account_use = (QList(response)
                   .where(lambda x: str(x.mt4AccountID) == service.config.app_data['mt4AccountID'])
                   .first())

    account_details = service.get_account_details(account_use.id)

    service_trades = ApiServiceTrades(cfg__oanda)
    open_trades = service_trades.get_trades_from_account(account_use.id)
    # endregion

    # region Build links
    ini['meterLink']['text'] = "Board"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(board_url)
    ini['meterLink']['tooltiptext'] = board_url

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

    # endregion

    # region Set dimensions
    ini['MeterDisplay']['W'] = '180'
    ini['MeterDisplay']['H'] = '300'
    ini['Variables']['ItemLines'] = '{0}'.format(len(open_trades) + 2)
    # endregion

    # region Build Dump
    dump = '{0}  {1}  $ {2:>10}\n'.format("TOTAL:", "UPL ", round(float(account_details.NAV), 2))
    for trade in open_trades:
        unrealized_profit_loss = round(float(trade['unrealizedPL']), 2)
        dump = dump + '{0}  {1}  $ {2:>10}\n'.format(str(trade['instrument']).replace('_', ''),
                                                     'SELL'if '-' in str(trade['currentUnits']) else 'BUY ',
                                                     '{0}{1}'.format('+' if '-' not in str(unrealized_profit_loss)
                                                                     else '',
                                                     str(round(unrealized_profit_loss, 2))),
                                               )
    # endregion

    return dump

