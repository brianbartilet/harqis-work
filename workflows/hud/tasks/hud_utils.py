import os
from pathlib import Path
import win32gui, win32process, psutil

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.resources.decorators import get_decorator_attrs
from core.utilities.logging.custom_logger import logger as log

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.corsair.profiles_mapping import build_summary
from apps.google_apps.references.constants import ScheduleCategory
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.tasks.sections import _sections__utilities_desktop, _sections__utilities_i_cue


from enum import Enum
from typing import Optional


class AppExe(str, Enum):
    DOCKER = "docker.exe"
    DOCKER_DESKTOP = "Docker Desktop.exe"
    DOCKER_BACKEND = "com.docker.backend.exe"
    DOCKER_BUILD = "com.docker.build.exe"

    CHROME = "chrome.exe"
    PYCHARM = "pycharm64.exe"
    SUBLIME_TEXT = "sublime_text.exe"
    RAINMETER = "Rainmeter.exe"
    MATTERMOST = "Mattermost.exe"
    SPOTIFY = "Spotify.exe"
    WEBEX = "WebexHost.exe"
    ICUE = "iCUE.exe"
    CELERY = "celery.exe"
    PYTHON = "python.exe"
    TERMINAL = "OpenConsole.exe"
    CMD = "cmd.exe"
    EXPLORER = "explorer.exe"
    # add more as needed...


# Example: profile names (iCUE / macros / HUD profiles etc.)
class Profile(str, Enum):
    BASE_MACROS_TO_COPY = "BASE_MACROS_TO_COPY_"
    BASE = "BASE_TO_COPY_"
    BROWSER = "Chrome"
    MARKDOWN = "Markdown"
    NAVIGATION = "Navigation"
    TEXT_EDITOR = "Notes"
    CODING = "PyCharm"
    CALL = "WEBEX"


# Map applications → profiles
APP_TO_PROFILE: dict[AppExe, Profile] = {

    # some sensible defaults (tweak however you want)
    AppExe.PYCHARM: Profile.CODING,
    AppExe.SUBLIME_TEXT: Profile.TEXT_EDITOR,
    AppExe.CELERY: Profile.NAVIGATION,
    AppExe.PYTHON: Profile.NAVIGATION,
    AppExe.CHROME: Profile.BROWSER,
    AppExe.EXPLORER: Profile.BROWSER,
    AppExe.WEBEX: Profile.CALL,
    AppExe.RAINMETER: Profile.BASE,
    AppExe.TERMINAL: Profile.BASE,
    AppExe.CMD: Profile.BASE,
}


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


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG,
            hud_item_name='HUD PROFILES',
            new_sections_dict=_sections__utilities_desktop,
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

    # region Build Dump
    dump = ""

    return dump


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG,
            hud_item_name='MOUSE BINDINGS',
            new_sections_dict=_sections__utilities_i_cue,
            play_sound=False,
            schedule_categories=[ScheduleCategory.ORGANIZE, ScheduleCategory.WORK]
            )
def show_mouse_bindings(cfg_id__desktop, ini=ConfigHelperRainmeter(), **kwargs):

    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))

    # region Corsair
    path = 'C:\Program Files\Corsair\Corsair iCUE5 Software\iCUE.exe'
    ini['meterLink']['Text'] = "ICue"
    ini['meterLink']['LeftMouseUpAction'] = '!Execute ["{0}"]'.format(path)
    ini['meterLink']['tooltiptext'] = path

    meta = get_decorator_attrs(show_mouse_bindings, prefix='')
    hud = str(meta['_hud_item_name']).replace(" ", "").upper()
    dump_path = '{0}'.format(os.path.join(RAINMETER_CONFIG['write_skin_to_path'],
                                          RAINMETER_CONFIG['skin_name'],
                                          hud, "dump.txt"
                                          ))
    ini['meterLink_dump']['Meter'] = 'String'
    ini['meterLink_dump']['MeterStyle'] = 'sItemLink'
    ini['meterLink_dump']['X'] = '(33*#Scale#)'
    ini['meterLink_dump']['Y'] = '(38*#Scale#)'
    ini['meterLink_dump']['W'] = '80'
    ini['meterLink_dump']['H'] = '55'
    ini['meterLink_dump']['Text'] = '|Dump'
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

    # region Build Dump
    cfg = CONFIG_MANAGER.get(cfg_id__desktop)
    path = Path(cfg['corsair']['path_profiles'])
    skin_dir = str(os.path.join(RAINMETER_CONFIG['write_skin_to_path'], RAINMETER_CONFIG['skin_name'], hud))

    combined_out_path, combined_dump, per_profile_outputs = build_summary(path, output_dir=skin_dir, per_profile_prefix="dump-")
    active_window_app = get_active_window_app()
    profile = get_profile_for_process_name(active_window_app).value

    ini['Variables']['TextFile'] = '#CURRENTPATH#dump-{0}.txt'.format(profile)

    return combined_dump