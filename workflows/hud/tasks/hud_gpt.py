import os
import re
from datetime import datetime, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.screenshot import ScreenshotUtility as screenshot
from core.utilities.data.strings import wrap_text, make_separator

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.helpers.feed import feed

from core.apps.gpt.assistants.base import BaseAssistant
from core.apps.gpt.models.assistants.message import MessageCreate
from core.apps.gpt.models.assistants.run import RunCreate
from core.utilities.logging.custom_logger import logger as log

from apps.google_apps.references.constants import ScheduleCategory
from apps.apps_config import CONFIG_MANAGER


TIMESTAMP_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")


def extract_first_last_timestamp(file_path: str):
    if not os.path.exists(file_path):
        return None, None

    first_ts = None
    last_ts = None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            match = TIMESTAMP_RE.search(line)
            if not match:
                continue

            ts_str = match.group(1)  # now "2025-11-26 10:04:28"

            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if first_ts is None:
                first_ts = ts

            last_ts = ts

    return first_ts, last_ts


_sections__check_desktop = {
    "meterLink_github": {
        "Preset": "InjectedByTest",
    },
}


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='GPT DESK CHECK', new_sections_dict=_sections__check_desktop,
            play_sound=False, schedule_categories=[ScheduleCategory.PINNED, ], prepend_if_exists=True)
@feed()
def get_helper_information(cfg_id__desktop, ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))
    # region Assistant Chat Setup
    assistant_chat = BaseAssistant()
    assistant_chat.load(assistant_id=assistant_chat.config.app_data['assistant_id_desktop'])

    cfg_id__desktop = CONFIG_MANAGER.get(cfg_id__desktop)

    def get_last_hour_pattern_actions_file():
        last_hour = datetime.now() - timedelta(hours=1)
        ts = last_hour.strftime("%Y%m%d_%H")
        return f"actions-{ts}.log"

    def ask_check_desktop():
        messages = [
            MessageCreate(role='user',
                          content='Analyze my desktop and try to understand what tasks am I doing based on the logs '
                                  'attached for the last hour containing information about focused and clicked items, open applications,'
                                  'ocr dump, clipboard data. Attached also are screenshots of of desktop monitors.'
                                  'Can you transcribe the information, provide a timeline of actions performed '
                                  'and then create an overall summary of tasks done for the past last hour.'
                                  'On the other hand, also provide suggestions on how to improve my productivity from the provided data,'
                                  'do some analysis and suggest other areas of interest I could explore. '
                                  'Perform some code analysis or review if there are some code data present.'
                                  'Make your replies in plain text paragraphs and do not use any markdown.'
                                  "Refrain from adding statement like here is your summary and do not provide a title, "
                                  "just chat box style replies"
                                  'Try to also skip sensitive data and information.'
                                  'Be insightful, detailed and be technical if possible, but still being be creative and relevant.'

                          ),
        ]
        # upload screenshots
        assistant_chat.add_messages_to_thread(messages)
        images_path = os.path.join(os.getcwd(), 'screenshots')
        assistant_chat.upload_files(images_path)
        # upload capture data
        capture_path = cfg_id__desktop['capture']['actions_log_path']
        patterns = [get_last_hour_pattern_actions_file(), ]
        assistant_chat.upload_files(capture_path, patterns)

        trigger = RunCreate(assistant_id=assistant_chat.properties.id,
                            tools = [{"type": "code_interpreter"}],
                            tool_resources={
                                                "code_interpreter": {
                                                    "file_ids": assistant_chat.attachments
                                                }
                                            }
                            )
        assistant_chat.run_thread(run=trigger)
        assistant_chat.wait_for_runs_to_complete()
        replies = assistant_chat.get_replies()
        answer = [x.content[0].text.value for x in replies]
        answer.sort(reverse=True)

        return answer

    path = os.path.join(os.getcwd(), 'screenshots')
    screenshot.take_screenshot_all_monitors(save_dir=path, prefix='screenshot-desktop-check')
    screenshot.cleanup_screenshots(save_dir=path, prefix='screenshot-desktop-check')
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
    file = os.path.join(
        cfg_id__desktop['capture']['actions_log_path'],
        get_last_hour_pattern_actions_file()
    )

    first_ts, last_ts = extract_first_last_timestamp(file)

    dump = "\n\n{0}\nSTART: {1}\n".format(make_separator(64), first_ts)

    answer_ = ask_check_desktop()
    dump += wrap_text(answer_, width=65, indent="\n")
    dump += "\n\nEND: {0}\n\n\n".format(last_ts)
    # endregion

    ini['Variables']['ItemLines'] = '{0}'.format(8)

    return dump


_sections__check_world_checks = {
    "meterLink_github": {
        "Preset": "InjectedByTest",
    },
}

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

