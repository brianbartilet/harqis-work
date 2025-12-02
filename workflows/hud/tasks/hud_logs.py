import os
import pprint
from pathlib import Path
from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result, get_index_data, LOGGING_INDEX
from core.utilities.data.schedulers import friendly_schedule
from core.utilities.data.strings import make_separator
from core.utilities.logging.custom_logger import logger as log
from core.utilities.resources.decorators import get_decorator_attrs
from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.desktop.helpers.feed import feed
from datetime import  datetime

from workflows.hud.tasks.sections import _sections__check_logs

from workflows.desktop.tasks_config import WORKFLOWS_DESKTOP
from workflows.hud.tasks_config import WORKFLOWS_HUD
from workflows.purchases.tasks_config import WORKFLOW_PURCHASES

from apps.google_apps.references.constants import ScheduleCategory


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='FAILED TASKS TODAY', new_sections_dict=_sections__check_logs, play_sound=False)
@feed()
def get_failed_jobs(ini=ConfigHelperRainmeter()):
    today = datetime.now().strftime("%Y-%m-%d")

    gte = f"{today}T00:00"
    lte = f"{today}T23:59"

    # region Get failed jobs from elasticsearch
    query = {
        "bool": {
            "must": [
                {
                    "range": {
                        "last_failed": {
                            "gte": gte,
                            "lte": lte
                        }
                    }
                }
            ]
        }
    }

    results = get_index_data(
        index_name=LOGGING_INDEX,
        query=query
    )
    # endregion

    # region Set links
    kibana_url = 'http://localhost:5601/app/dev_tools#/console'
    ini['meterLink']['text'] = "Kibana"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(kibana_url)
    ini['meterLink']['tooltiptext'] = kibana_url
    ini['meterLink']['W'] = '100'
    # endregion

    # region Set dimensions
    width_multiplier = 2.1
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    #ini['MeterDisplay']['MeasureName'] = 'MeasureLuaScriptScroll'

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
    dump = ""
    for hit in results:
        details = hit['_source']
        show_method = str(details['name']).split('.')[-2:]
        target_name = '.'.join(show_method)
        target_error = str(details['exception_message']).strip()
        dump += f"{target_name:<{42}} {target_error:>{8}}\n"



    if len(results) == 0:
        dump = dump + "Nothing to see here.\n"

    ini['Variables']['ItemLines'] = '{0}'.format(7)
    dump = dump + "\n"
    # endregion

    return dump


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='CELERY SPROUTS', new_sections_dict=_sections__check_logs,
            play_sound=False, schedule_categories=[ScheduleCategory.ORGANIZE, ])
@feed()
def get_schedules(ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))
    workflow_mapping = [
        WORKFLOWS_DESKTOP,
        WORKFLOWS_HUD,
        WORKFLOW_PURCHASES,
    ]
    # save to repo for some other use cases
    output_path = Path(os.path.join(os.getcwd(), "workflows.mapping"))
    # Use pprint to make it readable
    text = pprint.pformat(workflow_mapping, indent=4, width=120)
    output_path.write_text(text, encoding="utf-8")

    # region Set links
    meta = get_decorator_attrs(get_schedules, prefix='')
    hud = str(meta['_hud_item_name']).replace(" ", "").upper()
    dump_path = '{0}'.format(os.path.join(RAINMETER_CONFIG['write_skin_to_path'],
                                          RAINMETER_CONFIG['skin_name'],
                                          hud, "dump.txt"
                                          ))
    ini['meterLink']['text'] = "Dump"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]''!Execute ["{0}"]'.format(dump_path)
    ini['meterLink']['tooltiptext'] = dump_path
    ini['meterLink']['W'] = '100'


    # endregion

    # region Set dimensions
    width_multiplier = 1.3

    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*155*#Scale#)'.format(width_multiplier)
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
    dump = "\n"
    for wfd in workflow_mapping:
        for name, cfg in wfd.items():
            schedule = cfg.get("schedule")
            if schedule:
                human = friendly_schedule(schedule)
                task = cfg.get("task")
                wf, group, tasks, file, func = task.split('.')
                dump += f'{make_separator(36, "-")}\n{file}.{func:}\n > Triggers {human.lower()}\n'

    # endregion

    ini['Variables']['ItemLines'] = '{0}'.format(7)

    return dump
