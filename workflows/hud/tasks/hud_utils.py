from pathlib import Path

import os
import win32gui
import win32process
import psutil

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.corsair.profiles_mapping import build_summary
from apps.google_apps.references.constants import ScheduleCategory
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.dto.sections import sections__utilities_desktop, sections__utilities_i_cue, sections__utilities_ai
from workflows.hud.dto.constants import Profile, AppExe, HUD_NAME_MOUSE_BINDINGS, APP_TO_PROFILE


def get_profile_for_process_name(proc_name: str) -> Profile:
    """
    Given a process exe name like 'docker.exe', return the mapped Profile.
    Falls back to Profile.DEFAULT if not mapped.
    """
    proc_name = proc_name.strip().lower()

    for app in AppExe:
        if app.value.lower() == proc_name:
            return APP_TO_PROFILE.get(app, Profile.BASE)

    return Profile.BASE


def get_active_window_app(print_all=False):
    # get active window handle
    hwnd = win32gui.GetForegroundWindow()

    # get PID
    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    proc = psutil.Process(pid)

    active_name = proc.name()

    # --- NEW: list all open applications ---
    if print_all:
        open_apps = set()  # avoid duplicates

        for p in psutil.process_iter(['pid', 'name']):
            try:
                name = p.info['name']
                # Only include apps with a visible window
                hwnd = win32gui.FindWindow(None, None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            if name:
                open_apps.add(name)

        print("Active application:", active_name)
        print("Open applications:")
        for app in sorted(open_apps):
            print(" -", app)

    return active_name

    
@SPROUT.task(queue='hud')
@log_result()
@init_meter(RAINMETER_CONFIG,
            hud_item_name="HUD PROFILES",
            new_sections_dict=sections__utilities_desktop,
            play_sound=False)
def show_hud_profiles(ini=ConfigHelperRainmeter()):

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


    # region Build profiles office
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

    return ""


@SPROUT.task(queue='hud')
@log_result()
@init_meter(RAINMETER_CONFIG,
            hud_item_name=HUD_NAME_MOUSE_BINDINGS,
            new_sections_dict=sections__utilities_i_cue,
            play_sound=False,
            schedule_categories=[ScheduleCategory.ORGANIZE, ScheduleCategory.WORK]
            )
def show_mouse_bindings(ini=ConfigHelperRainmeter(), **kwargs):

    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))

    # region Corsair
    path = 'C:\Program Files\Corsair\Corsair iCUE5 Software\iCUE.exe'
    ini['meterLink']['Text'] = "ICUE"
    ini['meterLink']['LeftMouseUpAction'] = '!Execute ["{0}"]'.format(path)
    ini['meterLink']['tooltiptext'] = path

    hud = str(HUD_NAME_MOUSE_BINDINGS).replace(" ", "").upper()
    dump_path = '{0}'.format(os.path.join(RAINMETER_CONFIG['write_skin_to_path'],
                                          RAINMETER_CONFIG['skin_name'],
                                          hud
                                          ))
    ini['meterLink_dump']['Meter'] = 'String'
    ini['meterLink_dump']['MeterStyle'] = 'sItemLink'
    ini['meterLink_dump']['X'] = '(33*#Scale#)'
    ini['meterLink_dump']['Y'] = '(38*#Scale#)'
    ini['meterLink_dump']['W'] = '80'
    ini['meterLink_dump']['H'] = '55'
    ini['meterLink_dump']['Text'] = '|DUMP'
    ini['meterLink_dump']['LeftMouseUpAction'] = '!Execute ["{0}"]'.format(dump_path)
    ini['meterLink_dump']['tooltiptext'] = dump_path

    # region Set dimensions
    width_multiplier = 1.75
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)

    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*198*#Scale#)/2'.format(width_multiplier)

    ini['Variables']['ItemLines'] = '{0}'.format(15)
    # endregion

    active_window_app = get_active_window_app()
    profile = get_profile_for_process_name(active_window_app).value

    ini['Variables']['TextFile'] = '#CURRENTPATH#dump-{0}.txt'.format(profile)

    return "SUCCESS"


@SPROUT.task(queue='hud')
@log_result()
def build_summary_mouse_bindings(cfg_id__desktop):
    cfg = CONFIG_MANAGER.get(cfg_id__desktop)
    path = Path(cfg['corsair']['path_profiles'])
    skin_dir = str(os.path.join(RAINMETER_CONFIG['write_skin_to_path'], RAINMETER_CONFIG['skin_name'], HUD_NAME_MOUSE_BINDINGS
                                .replace(" ", "").upper()))

    combined_out_path, combined_dump, per_profile_outputs = build_summary(path, output_dir=skin_dir, per_profile_prefix="dump-")

    return combined_dump


@SPROUT.task(queue='hud')
@log_result()
@init_meter(RAINMETER_CONFIG,
            hud_item_name="AGENTS CORE",
            new_sections_dict=sections__utilities_ai,
            play_sound=False)
def show_ai_helper(cfg_id__n8n, cfg_id__eleven, cfg_id__py, ini=ConfigHelperRainmeter()):
    cfg_py = CONFIG_MANAGER.get(cfg_id__py)
    exe = cfg_py['bin']
    root = cfg_py['root']

    cfg_eleven = CONFIG_MANAGER.get(cfg_id__eleven)
    agent_voice = cfg_eleven['data']['assistants']['agent_n8n_automation']
    agent_chat_testing = cfg_eleven['data']['assistants']['agent_n8n_automation_chat_tests']
    agent_chat = cfg_eleven['data']['assistants']['agent_n8n_automation_chat']

    cfg_n8n = CONFIG_MANAGER.get(cfg_id__n8n)
    base_url = cfg_n8n.get('base_url', "http://localhost:5678")

    # region Build n8n link

    n8n_executions_url = "{0}/home/executions".format(base_url)
    ini['meterLink']['Text'] = "N8N EXECUTIONS"
    ini['meterLink']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(n8n_executions_url)
    ini['meterLink']['tooltiptext'] = n8n_executions_url
    ini['meterLink']['W'] = '200'

    ini['meterSeperator_n8n']['Meter'] = 'Image'
    ini['meterSeperator_n8n']['MeterStyle'] = 'styleSeperator'
    ini['meterSeperator_n8n']['Y'] = '(54*#Scale#)'

    # endregion

    # region Build link desktop chat agent
    ini['meterLink_agent_chat']['Text'] = "DESKTOP CHAT"
    cmd_chat = f'"{exe}" "{root}\\workflows\\n8n\\utilities\\assistant_widget.py" "{agent_chat}"'
    ini['meterLink_agent_chat']['LeftMouseUpAction'] = f'!Execute [{cmd_chat}]'

    ini['meterLink_agent_chat']['tooltiptext'] = "Run agent {0}".format(agent_chat)
    ini['meterLink_agent_chat']['Meter'] = 'String'
    ini['meterLink_agent_chat']['MeterStyle'] = 'sItemLink'
    ini['meterLink_agent_chat']['X'] = '(9*#Scale#)'
    ini['meterLink_agent_chat']['Y'] = '(58*#Scale#)'
    ini['meterLink_agent_chat']['W'] = '200'
    ini['meterLink_agent_chat']['H'] = '55'

    ini['meterSeperator_agent_chat']['Meter'] = 'Image'
    ini['meterSeperator_agent_chat']['MeterStyle'] = 'styleSeperator'
    ini['meterSeperator_agent_chat']['Y'] = '(74*#Scale#)'

    # endregion

    # region Build link desktop chat test agent
    ini['meterLink_agent_chat_tests']['Text'] = "DESKTOP CHAT TESTS"
    cmd_chat_tests = f'"{exe}" "{root}\\workflows\\n8n\\utilities\\assistant_widget.py" "{agent_chat_testing}"'
    ini['meterLink_agent_chat_tests']['LeftMouseUpAction'] = f'!Execute [{cmd_chat_tests}]'

    ini['meterLink_agent_chat_tests']['tooltiptext'] = "Run agent {0}".format(agent_chat_testing)
    ini['meterLink_agent_chat_tests']['Meter'] = 'String'
    ini['meterLink_agent_chat_tests']['MeterStyle'] = 'sItemLink'
    ini['meterLink_agent_chat_tests']['X'] = '(9*#Scale#)'
    ini['meterLink_agent_chat_tests']['Y'] = '(78*#Scale#)'
    ini['meterLink_agent_chat_tests']['W'] = '200'
    ini['meterLink_agent_chat_tests']['H'] = '55'

    ini['meterSeperator_agent_chat_tests']['Meter'] = 'Image'
    ini['meterSeperator_agent_chat_tests']['MeterStyle'] = 'styleSeperator'
    ini['meterSeperator_agent_chat_tests']['Y'] = '(94*#Scale#)'

    # endregion

    # region Build link desktop voice agent
    ini['meterLink_agent_voice']['Text'] = "DESKTOP VOICE"
    cmd_voice = f'"{exe}" "{root}\\workflows\\n8n\\utilities\\assistant_widget.py" "{agent_voice}"'
    ini['meterLink_agent_voice']['LeftMouseUpAction'] = f'!Execute [{cmd_voice}]'

    ini['meterLink_agent_voice']['tooltiptext'] = "Run agent {0}".format(agent_chat_testing)
    ini['meterLink_agent_voice']['Meter'] = 'String'
    ini['meterLink_agent_voice']['MeterStyle'] = 'sItemLink'
    ini['meterLink_agent_voice']['X'] = '(9*#Scale#)'
    ini['meterLink_agent_voice']['Y'] = '(98*#Scale#)'
    ini['meterLink_agent_voice']['W'] = '200'
    ini['meterLink_agent_voice']['H'] = '55'

    ini['meterSeperator_agent_voice']['Meter'] = 'Image'
    ini['meterSeperator_agent_voice']['MeterStyle'] = 'styleSeperator'
    ini['meterSeperator_agent_voice']['Y'] = '(114*#Scale#)'

    # endregion


    # region Set dimensions
    ini['MeterDisplay']['W'] = '180'
    ini['MeterDisplay']['H'] = '350'
    ini['Variables']['ItemLines'] = '{0}'.format(4)
    # endregion

    return ""
