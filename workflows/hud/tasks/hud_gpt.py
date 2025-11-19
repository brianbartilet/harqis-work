import os
import re

from core.apps.sprout.app.celery import SPROUT
from core.utilities.screenshot import ScreenshotUtility as screenshot
from core.utilities.data.strings import wrap_text

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_config
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG

from core.apps.gpt.assistants.base import BaseAssistant
from core.apps.gpt.models.assistants.message import MessageCreate
from core.apps.gpt.models.assistants.run import RunCreate

_sections__check_desktop = {
    "meterLink_github": {
        "Preset": "InjectedByTest",
    },
}


@SPROUT.task()
@init_config(RAINMETER_CONFIG,
             hud_item_name='GPT DESK CHECK',
             new_sections_dict=_sections__check_desktop,
             play_sound=False)
def get_helper_information(ini=ConfigHelperRainmeter()):
    assistant_chat = BaseAssistant()
    assistant_chat.load(assistant_id=assistant_chat.config.app_data['default_assistant_id_desktop'])

    def ask_check_desktop():
        messages = [
            MessageCreate(role='user',
                          content='Analyze my desktop and try to understand what I am doing and possible tasks along '
                                  'with screenshots of my desktop and open applications. '
                                  'Provide suggestions on how to improve my productivity based on what you see '
                                  'and if possible do some coding analysis and suggest other areas if I am consuming media.'
                                  'Make it in a few plain text bullet points (less than 8) and do not use markdown.'
                                  'Be super concise do not explain yourself and but try to be creative and relevant. '),
        ]
        assistant_chat.add_messages_to_thread(messages)
        path = os.path.join(os.getcwd(), 'screenshots')
        assistant_chat.upload_files(path)
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
    screenshot.take_screenshot_all_windows(save_dir=path)

    answer_ = ask_check_desktop()
    screenshot.cleanup_screenshots()

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

    width_multiplier = 2.3
    ini['MeterDisplay']['W'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '1000'

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*187),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackground']['H'] = ''
    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*190*#Scale#)/2'.format(width_multiplier)

    dump = wrap_text(answer_, width=65)

    ini['Variables']['ItemLines'] = '{0}'.format(len(re.findall(r'\r\n|\r|\n', dump)))

    return dump

