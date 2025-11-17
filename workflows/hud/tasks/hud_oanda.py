from random import randint

from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import logger as log
from core.utilities.data.qlist import QList

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_config
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.oanda.references.web.api.account import ApiServiceOandaAccount

from apps.apps_config import CONFIG_MANAGER


@SPROUT.task()
def task_smoke():
    """Test function to add two numbers and return the result."""
    number = randint(1, 100) + randint(1, 100)
    log.info("Running a test result {0}".format(number))
    return number


_sections_config__account_oanda = {
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
             hud_item_name='OANDA ACCOUNT',
             play_sound=True,
             new_sections_dict=_sections_config__account_oanda
             )
def show_account_information(cfg_id__oanda, ini=ConfigHelperRainmeter()):

    cfg__oanda = CONFIG_MANAGER.get(cfg_id__oanda)

    board_url = "https://trello.com/b/351MWTYe/daily-dashboard-trading"

    service = ApiServiceOandaAccount(cfg__oanda)
    response = service.get_account_info()

    account_use = (QList(response)
                   .where(lambda x: str(x.mt4AccountID) == service.config.app_data['mt4AccountID'])
                   .first())

    account_details = service.get_account_details(account_use.id)

    #service_trades = ApiServiceOandaAccount(oanda_id)
    #open_trades = service_trades.get_trades_from_account(account_use.id)
    open_trades = []

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
    ini['meterLink_broker']['W'] = '181'
    ini['meterLink_broker']['H'] = '14'
    ini['meterLink_broker']['StringStyle'] = 'Italic'
    ini['meterLink_broker']['Text'] = '|Broker'
    ini['meterLink_broker']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(broker_url)
    #  endregion

    #  region Section: meterLink_news
    news_url = 'https://www.myfxbook.com/forex-economic-calendar'
    ini['meterLink_news']['Meter'] = 'String'
    ini['meterLink_news']['MeterStyle'] = 'sItemLink'
    ini['meterLink_news']['X'] = '(82*#Scale#)'
    ini['meterLink_news']['Y'] = '(38*#Scale#)'
    ini['meterLink_news']['W'] = '181'
    ini['meterLink_news']['H'] = '14'
    ini['meterLink_news']['StringStyle'] = 'Italic'
    ini['meterLink_news']['Text'] = '|News'
    ini['meterLink_news']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(news_url)
    #  endregion

    #  region Section: meterlink_metrics
    url = 'http://localhost:3001/'
    ini['meterLink_metrics']['Meter'] = 'String'
    ini['meterLink_metrics']['MeterStyle'] = 'sItemLink'
    ini['meterLink_metrics']['X'] = '(112*#Scale#)'
    ini['meterLink_metrics']['Y'] = '(38*#Scale#)'
    ini['meterLink_metrics']['W'] = '181'
    ini['meterLink_metrics']['H'] = '14'
    ini['meterLink_metrics']['StringStyle'] = 'Italic'
    ini['meterLink_metrics']['Text'] = '|Metrics'
    ini['meterLink_metrics']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(url)
    #  endregion

    #ini['MeterDisplay']['W'] = '180'
    #ini['MeterDisplay']['H'] = '300'

    #dump = '{0}  {1}  $ {2:>10}\n'.format("TOTAL:", "UPL ", round(float(account_details.unrealized_pl), 2))
    dump = '{0}  {1}  $ {2:>10}\n'.format("TOTAL:", "UPL ", round(float(0), 2))
    for trade in open_trades:
        unrealized_profit_loss = round(float(trade.unrealized_pl), 2)
        dump = dump + '{0}  {1}  $ {2:>10}\n'.format(str(trade.instrument).replace('_', ''),
                                                     'SELL'if '-' in str(trade.current_units) else 'BUY ',
                                                     '{0}{1}'.format('+' if '-' not in str(unrealized_profit_loss)
                                                                     else '',
                                                     str(round(unrealized_profit_loss, 2))),
                                               )

    return dump

