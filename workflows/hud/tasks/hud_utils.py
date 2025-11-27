from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.tasks.sections import _sections__utilities_desktop


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='HUD PROFILES', new_sections_dict=_sections__utilities_desktop, play_sound=False)
def generate_utils_profiles(ini=ConfigHelperRainmeter()):

    # region Build profiles home
    profile_base = "home"
    ini['meterLink']['Text'] = "SAVE"
    ini['meterLink']['LeftMouseUpAction'] = '!Manage Layouts'.format(profile_base)
    ini['meterLink']['tooltiptext'] = "Save layout changes for {0}".format(profile_base)

    ini['meterLink_home']['Meter'] = 'String'
    ini['meterLink_home']['MeterStyle'] = 'sItemLink'
    ini['meterLink_home']['X'] = '(36*#Scale#)'
    ini['meterLink_home']['Y'] = '(38*#Scale#)'
    ini['meterLink_home']['W'] = '100'
    ini['meterLink_home']['H'] = '55'
    ini['meterLink_home']['Text'] = '| LOAD {0}'.format(profile_base.capitalize())
    ini['meterLink_home']['LeftMouseUpAction'] = '!LoadLayout "{0}"'.format(profile_base)
    ini['meterLink_home']['tooltiptext'] = "Switch hud to {0}".format(profile_base)

    ini['meterSeperator_home']['Meter'] = 'Image'
    ini['meterSeperator_home']['MeterStyle'] = 'styleSeperator'
    ini['meterSeperator_home']['Y'] = '(54*#Scale#)'


    # region Build profiles home
    profile_office = "office"
    ini['meterLink_office_save']['Text'] = "SAVE"
    ini['meterLink_office_save']['LeftMouseUpAction'] = '!Manage Layouts'.format(profile_office)
    ini['meterLink_office_save']['tooltiptext'] = "Save layout changes for {0}".format(profile_office)
    ini['meterLink_office_save']['Meter'] = 'String'
    ini['meterLink_office_save']['MeterStyle'] = 'sItemLink'
    ini['meterLink_office_save']['X'] = '(9*#Scale#)'
    ini['meterLink_office_save']['Y'] = '(58*#Scale#)'
    ini['meterLink_office_save']['W'] = '60'
    ini['meterLink_office_save']['H'] = '55'

    ini['meterLink_office']['Meter'] = 'String'
    ini['meterLink_office']['MeterStyle'] = 'sItemLink'
    ini['meterLink_office']['X'] = '(36*#Scale#)'
    ini['meterLink_office']['Y'] = '(58*#Scale#)'
    ini['meterLink_office']['W'] = '100'
    ini['meterLink_office']['H'] = '55'
    ini['meterLink_office']['Text'] = '| LOAD {0}'.format(profile_office.capitalize())
    ini['meterLink_office']['LeftMouseUpAction'] = '!LoadLayout "{0}"'.format(profile_office)
    ini['meterLink_office']['tooltiptext'] = "Switch hud to {0}".format(profile_office)

    ini['meterSeperator_office']['Meter'] = 'Image'
    ini['meterSeperator_office']['MeterStyle'] = 'styleSeperator'
    ini['meterSeperator_office']['Y'] = '(74*#Scale#)'

    # endregion

    # region Build profiles custom
    profile_custom = "custom"
    ini['meterLink_custom_save']['Text'] = "SAVE"
    ini['meterLink_custom_save']['LeftMouseUpAction'] = '!Manage Layouts'.format(profile_custom)
    ini['meterLink_custom_save']['tooltiptext'] = "Save layout changes for {0}".format(profile_custom)
    ini['meterLink_custom_save']['Meter'] = 'String'
    ini['meterLink_custom_save']['MeterStyle'] = 'sItemLink'
    ini['meterLink_custom_save']['X'] = '(9*#Scale#)'
    ini['meterLink_custom_save']['Y'] = '(78*#Scale#)'
    ini['meterLink_custom_save']['W'] = '60'
    ini['meterLink_custom_save']['H'] = '55'

    ini['meterLink_custom']['Meter'] = 'String'
    ini['meterLink_custom']['MeterStyle'] = 'sItemLink'
    ini['meterLink_custom']['X'] = '(36*#Scale#)'
    ini['meterLink_custom']['Y'] = '(78*#Scale#)'
    ini['meterLink_custom']['W'] = '100'
    ini['meterLink_custom']['H'] = '55'
    ini['meterLink_custom']['Text'] = '| LOAD {0}'.format(profile_custom.capitalize())
    ini['meterLink_custom']['LeftMouseUpAction'] = '!LoadLayout "{0}"'.format(profile_custom)
    ini['meterLink_custom']['tooltiptext'] = "Switch hud to {0}".format(profile_custom)

    ini['meterSeperator_custom']['Meter'] = 'Image'
    ini['meterSeperator_custom']['MeterStyle'] = 'styleSeperator'
    ini['meterSeperator_custom']['Y'] = '(94*#Scale#)'

    # endregion

    # region Set dimensions
    ini['MeterDisplay']['W'] = '180'
    ini['MeterDisplay']['H'] = '300'
    ini['Variables']['ItemLines'] = '{0}'.format(3)
    # endregion

    # region Build Dump
    dump = ""

    return dump


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='LINKS - ', new_sections_dict=_sections__utilities_desktop, play_sound=False)
def generate_utilities2(cfg_id__desktop, ini=ConfigHelperRainmeter()):

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