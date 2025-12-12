import os
import re
from datetime import datetime, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from core.apps.gpt.assistants.base import BaseAssistant
from core.apps.gpt.models.assistants.message import MessageCreate
from core.apps.gpt.models.assistants.run import RunCreate
from core.utilities.logging.custom_logger import logger as log
from core.utilities.files import zip_folder, copy_files_to_folder, get_all_files
from core.utilities.resources.decorators import get_decorator_attrs
from core.utilities.screenshot import ScreenshotUtility as screenshot
from core.utilities.data.strings import wrap_text, make_separator

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.helpers.feed import feed

from apps.google_apps.references.constants import ScheduleCategory
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.dto.sections import sections__check_desktop, sections__check_world_checks


@SPROUT.task(queue='hud')
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='DESKTOP LOGS', new_sections_dict=sections__check_desktop,
            play_sound=True, schedule_categories=[ScheduleCategory.PINNED, ], prepend_if_exists=True)
@feed()
def get_desktop_logs(cfg_id__desktop, timedelta_previous_hours = 1, ini=ConfigHelperRainmeter(), **kwargs):

    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))
    # region Assistant Chat Setup Functions
    no_connection = False
    try:
        assistant_chat = BaseAssistant()
        assistant_chat.load(assistant_id=assistant_chat.config.app_data['assistant_id_desktop'])
    except Exception:
        no_connection = True

    cfg_id__desktop = CONFIG_MANAGER.get(cfg_id__desktop)

    def extract_first_last_timestamp(file_path: str):
        timestamp_re = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})]")
        first = None
        last = None

        if not os.path.exists(file_path):
            return None, None
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                match = timestamp_re.search(line)
                if not match:
                    continue

                ts_str = match.group(1)

                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

                if first is None:
                    first = ts

                last = ts

        return first, last

    def collect_files(timedelta_hours = 1):
        """
        :param timedelta_hours: hours behind to check
        :return:
        """
        capture_path = cfg_id__desktop['capture']['actions_log_path']
        archive_path = cfg_id__desktop['capture']['archive_path']

        # generate, gather and archive screenshots, there should be a separate task taking desktop at an interval
        last_hour = datetime.now() - timedelta(hours=timedelta_hours)
        path = cfg_id__desktop['capture']['screenshots_path']
        ts_last_hour = last_hour.strftime("%Y-%m-%d-%H")
        files_last_hour = get_all_files(path, ts_last_hour)
        folder_to_zip = f'sc-archive-{ts_last_hour}'
        zip_file_name = f'sc-archive-{ts_last_hour}.zip'
        copy_files_to_folder(archive_path, folder_name=folder_to_zip, file_names_list=files_last_hour)

        # find actions file and move to archive folder
        # Format using the actual date of that hour
        ts = last_hour.strftime("%Y%m%d_%H")
        actions_file = f"actions-{ts}.log"
        move_action_file_path = os.path.join(capture_path, actions_file)
        copy_files_to_folder(archive_path, folder_name=folder_to_zip, file_names_list=[move_action_file_path, ])

        zip_file = os.path.join(archive_path, zip_file_name)
        zip_folder(os.path.join(archive_path, folder_to_zip), zip_file)

        assistant_chat.upload_files(archive_path, [f'{zip_file_name}', ])

        return move_action_file_path

    def ask_check_desktop():
        messages = [
            MessageCreate(role='user',
                          content=
                          """
                          You are an analysis assistant. Analyze ONLY the contents of the provided ZIP file.
                          Data handling:
                          Unpack and read every file in the ZIP.
                          Treat the activity log as the authoritative source of truth.
                          Use screenshots only to confirm or enrich log data with visible UI context; if text is unreadable, say it is unreadable.
                          
                          Allowed reasoning:
                          Extract facts explicitly present in the logs and screenshots.
                          You may label an “AFK/idle” period only when the log shows a clear event gap.
                          You may use the user’s timezone only to contextualize timestamps that already exist in the ZIP.
                          Do NOT infer what happened during gaps.
                          
                          You may NOT:
                          Invent applications, actions, windows, text, or timestamps.
                          Guess file names or metadata that are not present.
                          Fill gaps with imagined activity.
                          Attribute motivation, intent, or emotion.
                          
                          Required analysis (evidence only):
                          Reconstruct desktop behavior: focus changes, clipboard events, OCR text (only if readable), opened apps, window titles, and interaction sequences.
                          Identify likely tasks only when strongly supported by the artifacts; otherwise state “cannot be determined”.
                          Detect and describe idle/AFK periods from event gaps.
                          Do not conclude “offline/out for the day/asleep” unless the ZIP includes direct evidence; otherwise state “cannot be determined”.
                          Provide optional productivity improvement suggestions only if directly supported by observed patterns; otherwise omit.
                          
                          Output requirements:
                          No headers, bullet points, titles, lists, or markdown formatting.
                          Continuous paragraphs, each reflecting a meaningful activity cluster.
                          Use timestamps sparingly and only when needed for transitions or inactivity.
                          No introductions, disclaimers, conclusions, or process narration.
                          Single uninterrupted output.
                          Do not ask questions.
                          
                          Accuracy enforcement:
                          If something cannot be confirmed from the ZIP, explicitly say it cannot be determined.
                          Prefer omission over invention.
                          All statements must be traceable to evidence inside the ZIP.
                          """
                          )
        ]

        assistant_chat.add_messages_to_thread(messages)
        trigger = RunCreate(
            assistant_id=assistant_chat.properties.id,
            tools = [{"type": "code_interpreter"}],
            tool_resources={ "code_interpreter": { "file_ids": assistant_chat.attachments }}
        )
        assistant_chat.run_thread(run=trigger)
        assistant_chat.wait_for_runs_to_complete(wait_secs=30, retries=20)
        replies = assistant_chat.get_replies()
        answer = []
        for x in replies:
            try:
                answer.append(x.content[0].text.value)
            except (AttributeError, IndexError, KeyError):
                last_hour = datetime.now() - timedelta(hours=1)
                ts_last_hour = last_hour.strftime("%Y-%m-%d-%H")
                answer.append(f'AFK {ts_last_hour}\n\n')
                continue
        answer.sort(reverse=True)

        return answer

    # endregion

    # region Set links
    chat_url = 'https://chatgpt.com/'
    ini['meterLink']['text'] = "CHEATGPT"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(chat_url)
    ini['meterLink']['tooltiptext'] = chat_url
    ini['meterLink']['W'] = '100'

    github_work_url = 'https://github.com/brianbartilet/harqis-work'
    ini['meterLink_github']['Meter'] = 'String'
    ini['meterLink_github']['MeterStyle'] = 'sItemLink'
    ini['meterLink_github']['X'] = '(58*#Scale#)'
    ini['meterLink_github']['Y'] = '(38*#Scale#)'
    ini['meterLink_github']['W'] = '80'
    ini['meterLink_github']['H'] = '55'
    ini['meterLink_github']['Text'] = '|GITHUB'
    ini['meterLink_github']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(github_work_url)
    ini['meterLink_github']['tooltiptext'] = github_work_url

    meta = get_decorator_attrs(get_desktop_logs, prefix='')
    hud = str(meta['_hud_item_name']).replace(" ", "").upper()
    dump_path = '{0}'.format(os.path.join(RAINMETER_CONFIG['write_skin_to_path'],
                                          RAINMETER_CONFIG['skin_name'],
                                          hud, "dump.txt"
                                          ))
    ini['meterLink_dump']['Meter'] = 'String'
    ini['meterLink_dump']['MeterStyle'] = 'sItemLink'
    ini['meterLink_dump']['X'] = '(100*#Scale#)'
    ini['meterLink_dump']['Y'] = '(38*#Scale#)'
    ini['meterLink_dump']['W'] = '80'
    ini['meterLink_dump']['H'] = '55'
    ini['meterLink_dump']['Text'] = '|DUMP'
    ini['meterLink_dump']['LeftMouseUpAction'] = '!Execute ["{0}"]'.format(dump_path)
    ini['meterLink_dump']['tooltiptext'] = dump_path

    # endregion

    # region Set dimensions
    width_multiplier = 2.25
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)

    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    ini['MeterDisplay']['MeasureName'] = 'MeasureLuaScriptScroll'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*198*#Scale#)/2'.format(width_multiplier)
    # endregion

    # region Dump data
    log_file = None
    try:
        log_file = collect_files(timedelta_previous_hours)
    except Exception:
        no_connection = True

    file = os.path.join(cfg_id__desktop['capture']['actions_log_path'],
        f'{log_file}'
    )

    if log_file:
        first_ts, last_ts = extract_first_last_timestamp(file)
    else:
        now = datetime.now()
        last_hour = datetime.now() - timedelta(hours=timedelta_previous_hours)
        ts_last_hour = last_hour.strftime("%Y-%m-%d-%H")
        ts_now = now.strftime("%Y-%m-%d-%H")

        first_ts, last_ts = ts_now, ts_last_hour
    dump = ""
    dump += "\n\n{0}\n[START] {1}\n".format(make_separator(64), first_ts)

    answer_ = []
    try:
        answer_ = ask_check_desktop()
    except Exception:
        no_connection = True

    if no_connection or len(answer_) == 0:
        dump += "\nCannot process logs. No connection or no data collected.\n\n"

    dump += wrap_text(answer_, width=65, indent="\n")
    dump += "\n\n[END]   {0}\n\n\n".format(last_ts)
    # endregion

    ini['Variables']['ItemLines'] = '{0}'.format(7)

    return dump


@SPROUT.task(queue='hud')
@log_result()
@init_meter(RAINMETER_CONFIG,
            hud_item_name='GPT INFO', new_sections_dict=sections__check_world_checks, play_sound=False,
            schedule_categories=[ScheduleCategory.WORK, ])
def get_events_world_check(countries_list=None, utc_tz="UTC+8", ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))

    if countries_list is None:
        return "No countries specified.\n\n\n"

    # region Assistant Chat Setup
    assistant_chat = BaseAssistant()
    assistant_chat.load(assistant_id=assistant_chat.config.app_data['assistant_id_reporter'])

    def ask_check_events():
        messages = [
            MessageCreate(role='user',
                          content='Given the list of countries: {0}'
                                  'Can you get the following information:'
                                  '- Display their current time if my timezone is {1}'
                                  '- Weather today from each country'
                                  '- Notable events that happened today or this week'
                                  'Make your reply in a plain text paragraphs no bullet points or numbers and do not use markdown.'
                                  'Be accurate and relevant.'.format(", ".join(countries_list), utc_tz)),
        ]
        assistant_chat.add_messages_to_thread(messages)
        trigger = RunCreate(assistant_id=assistant_chat.properties.id)
        assistant_chat.run_thread(run=trigger)
        assistant_chat.wait_for_runs_to_complete()
        replies = assistant_chat.get_replies()
        answer = [x.content[0].text.value for x in replies]
        answer.sort(reverse=True)

        return answer

    # endregion

    # region Set links
    chat_url = 'https://chatgpt.com/'
    ini['meterLink']['text'] = "CheatGPT"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(chat_url)
    ini['meterLink']['tooltiptext'] = chat_url
    ini['meterLink']['W'] = '100'

    github_work_url = 'https://github.com/brianbartilet/harqis-work'
    ini['meterLink_github']['Meter'] = 'String'
    ini['meterLink_github']['MeterStyle'] = 'sItemLink'
    ini['meterLink_github']['X'] = '(60*#Scale#)'
    ini['meterLink_github']['Y'] = '(38*#Scale#)'
    ini['meterLink_github']['W'] = '80'
    ini['meterLink_github']['H'] = '55'
    ini['meterLink_github']['Text'] = '|GitHub'
    ini['meterLink_github']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(github_work_url)
    ini['meterLink_github']['tooltiptext'] = github_work_url
    # endregion

    # region Set dimensions
    width_multiplier = 2.25
    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    ini['MeterDisplay']['MeasureName'] = 'MeasureLuaScriptScroll'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*198*#Scale#)/2'.format(width_multiplier)
    # endregion

    # region Dump data

    answer_ = ask_check_events()
    dump = wrap_text(answer_, width=65, indent="\n")

    # endregion

    ini['Variables']['ItemLines'] = '{0}'.format(8)

    return dump


@SPROUT.task(queue='default')
@log_result()
@feed()
def take_screenshots_for_gpt_capture(cfg_id__desktop):
    cfg = CONFIG_MANAGER.get(cfg_id__desktop)
    path = cfg['capture']['screenshots_path']
    now = datetime.now()
    ts = now.strftime(cfg['capture']['strf_time'])
    screenshot.take_screenshot_all_monitors(save_dir=path, prefix=f'{ts}-sc-desktop-check')

    return "SUCCESS"


