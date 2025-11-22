from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result, get_index_data, LOGGING_INDEX
from core.utilities.data.strings import make_separator
from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from datetime import  datetime

_sections__check_logs = {
    "meterLink_elastic": {
        "Preset": "InjectedByTest",
    },
}


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='FAILED TASKS TODAY', new_sections_dict=_sections__check_logs, play_sound=False)
def get_failed_jobs(ini=ConfigHelperRainmeter()):
    today = datetime.now().strftime("%Y-%m-%d")

    gte = f"{today}T00:00"
    lte = f"{today}T23:59"

    print("Today Errors:")
    print("From:", gte)
    print("To:  ", lte)

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
    width_multiplier = 1.7
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

    dump = "{0}\n".format(make_separator(48, char="="))
    line_ctr = 1
    for hit in results:
        line_ctr += 1
        details = hit['_source']
        show_method = str(details['name']).split('.')[-2:]
        target_name = '.'.join(show_method)
        target_error = details['exception_message']
        target_error = ""
        dump = dump + '{0:<35} {1:>10}\n'.format(target_name, target_error)

    # endregion
    if len(results) == 0:
        dump = dump + "No failed jobs today!\n"

    ini['Variables']['ItemLines'] = '{0}'.format(6)
    dump = dump + "\n"
    return dump
