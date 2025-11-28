import os
import re
from datetime import datetime, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from core.apps.gpt.assistants.base import BaseAssistant
from core.apps.gpt.models.assistants.message import MessageCreate
from core.apps.gpt.models.assistants.run import RunCreate
from core.utilities.logging.custom_logger import logger as log
from core.utilities.files import zip_folder
from core.utilities.resources.decorators import get_decorator_attrs
from core.utilities.screenshot import ScreenshotUtility as screenshot
from core.utilities.data.strings import wrap_text, make_separator

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.helpers.feed import feed

from apps.google_apps.references.constants import ScheduleCategory
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.tasks.sections import _sections__check_desktop, _sections__check_world_checks


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='GPT DESK CHECK', new_sections_dict=_sections__check_desktop,
            play_sound=True, schedule_categories=[ScheduleCategory.PINNED, ], prepend_if_exists=True)
@feed()
def get_helper_information(cfg_id__desktop, ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))
    # region Assistant Chat Setup Functions
    assistant_chat = BaseAssistant()
    assistant_chat.load(assistant_id=assistant_chat.config.app_data['assistant_id_desktop'])

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

    def get_last_hour_pattern_actions_file():
        # Get local time
        now = datetime.now()

        # Always subtract one hour — automatically handles midnight rollover
        last_hour = now - timedelta(hours=1)

        # Format using the actual date of that hour
        ts = last_hour.strftime("%Y%m%d_%H")
        return f"actions-{ts}"

    def ask_check_desktop():
        messages = [
            MessageCreate(role='user',
                          content="Analyze the attached desktop activity logs and screenshots."
                                  "The attached files all necessary information and please do not ask for any further clarifications. "
                                  "Process only the most recent hour found in the files. "
                                  "Please explicitly add details from used and opened applications or from focus or click actions, "
                                  "mention the application interacted with and figure out what I was doing."
                                  "Focus on behaviour, patterns, window movements, files interacted with, tools accessed, "
                                  "and what tasks I'm like performing."
                                  "The logs contain all events such as focus changes, clicks, clipboard activity, OCR text, "
                                  "and opened application entries."
                                  "Generate a clear, third-person bullet-point summary describing the desktop activity. "
                                  "Do not use timestamps."
                                  "Detect and explicitly note any periods of AFK, idle behaviour, or lack of interaction."
                                  "Also figure out if I'm already out for the day or asleep based on my timezone, "
                                  "based on patterns such as missing focus changes, absence of clicks, or long gaps in activity."
                                  "Add optional details on how can I improve productivity from analyzed activities"
                                  "Do not add headers, markdown, introductions, or conclusions."
                                  "Do not ask any questions."
                                  "Produce exactly one uninterrupted answer. Base everything strictly on the logs, "
                                  "but make reasonable assumptions to fill in missing context where helpful."
                                  "Write only clean bullet points that read like an observer’s highlights of the hour’s activity."
                          )
        ]
        # upload capture data
        pattern_item = get_last_hour_pattern_actions_file()
        capture_path = cfg_id__desktop['capture']['actions_log_path']
        archive_path = cfg_id__desktop['capture']['archive_path']
        zip_file = os.path.join(archive_path, f'{pattern_item}.zip')
        zip_folder(capture_path, zip_file)

        assistant_chat.upload_files(capture_path, [f'{pattern_item}.log', ])
        assistant_chat.upload_files(archive_path, [f'{pattern_item}.zip', ])

        # upload screenshots
        images_path = os.path.join(os.getcwd(), 'screenshots')
        assistant_chat.upload_files(images_path)

        assistant_chat.add_messages_to_thread(messages)
        trigger = RunCreate(
            assistant_id=assistant_chat.properties.id,
            tools = [{"type": "code_interpreter"}],
            tool_resources={ "code_interpreter": { "file_ids": assistant_chat.attachments }}
        )
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
    ini['meterLink_github']['X'] = '(58*#Scale#)'
    ini['meterLink_github']['Y'] = '(38*#Scale#)'
    ini['meterLink_github']['W'] = '80'
    ini['meterLink_github']['H'] = '55'
    ini['meterLink_github']['Text'] = '|GitHub'
    ini['meterLink_github']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(github_work_url)
    ini['meterLink_github']['tooltiptext'] = github_work_url

    meta = get_decorator_attrs(get_helper_information, prefix='')
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
    ini['meterLink_dump']['Text'] = '|Dump'
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

    path = os.path.join(os.getcwd(), 'screenshots')
    screenshot.take_screenshot_all_monitors(save_dir=path, prefix='screenshot-desktop-check')

    file = os.path.join(cfg_id__desktop['capture']['actions_log_path'],
        f'{get_last_hour_pattern_actions_file()}.log'
    )

    first_ts, last_ts = extract_first_last_timestamp(file)

    dump = "\n\n{0}\nSTART: {1}\n".format(make_separator(64), first_ts)

    answer_ = ask_check_desktop()
    dump += wrap_text(answer_, width=65, indent="\n")
    dump += "\n\nEND: {0}\n\n\n".format(last_ts)
    # endregion

    ini['Variables']['ItemLines'] = '{0}'.format(7)

    screenshot.cleanup_screenshots(save_dir=path, prefix='screenshot-desktop-check')

    return dump


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG,
            hud_item_name='GPT INFO', new_sections_dict=_sections__check_world_checks, play_sound=False,
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

