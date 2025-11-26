from datetime import datetime

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.data.strings import make_separator
from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents, EventType
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.tasks.sections import _sections__utilities_desktop




@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='UTILITIES', new_sections_dict=_sections__utilities_desktop, play_sound=False)
def generate_utilities(cfg_id__desktop, ini=ConfigHelperRainmeter()):

    # region Fetch OANDA data
    cfg__desktop = CONFIG_MANAGER.get(cfg_id__desktop)

    # endregion

    # region Build profiles
    profile_base =  "office"
    ini['meterLink']['Text'] = profile_base.capitalize()
    ini['meterLink']['LeftMouseUpAction'] = '!LoadLayout "{0}"'.format(profile_base)
    ini['meterLink']['tooltiptext'] = "Switch hud to {0}".format(profile_base)

    profile_home = "home"
    ini['meterLink_office']['Meter'] = 'String'
    ini['meterLink_office']['MeterStyle'] = 'sItemLink'
    ini['meterLink_office']['X'] = '(45*#Scale#)'
    ini['meterLink_office']['Y'] = '(38*#Scale#)'
    ini['meterLink_office']['W'] = '60'
    ini['meterLink_office']['H'] = '55'
    ini['meterLink_office']['Text'] = '|{0}'.format(profile_home.capitalize())
    ini['meterLink_office']['LeftMouseUpAction'] = '!LoadLayout "{0}"'.format(profile_home)
    ini['meterLink_office']['tooltiptext'] = "Switch hud to {0}".format(profile_home)


    # endregion

    # region Set dimensions
    ini['MeterDisplay']['W'] = '180'
    ini['MeterDisplay']['H'] = '300'
    ini['Variables']['ItemLines'] = '{0}'.format(2)
    # endregion

    # region Build Dump
    dump = ""

    return dump

