from datetime import datetime

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.data.strings import make_separator
from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents, EventType
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.tasks.sections import _sections__calendar


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='CALENDAR PEEK', new_sections_dict=_sections__calendar, play_sound=False)
@feed()
def show_calendar_information(cfg_id__gsuite, ini=ConfigHelperRainmeter()):

    # region Fetch events and filter
    cfg__gsuite= CONFIG_MANAGER.get(cfg_id__gsuite)
    service = ApiServiceGoogleCalendarEvents(cfg__gsuite)
    events_today_all_day = service.get_all_events_today(EventType.ALL_DAY)
    events_today_now = service.get_all_events_today(EventType.NOW)
    events_today_upcoming = service.get_all_events_today(EventType.SCHEDULED)

    events_today_filtered = []
    for event in events_today_all_day:
        for current_block in events_today_now:
            if event['calendarSummary'] == current_block['calendarSummary']:
                events_today_filtered.append(event)
            else:
                continue

    # endregion

    # region Build Links
    calendar_url = "https://calendar.google.com/calendar/u/0/r"
    ini['meterLink']['text'] = "Calendar"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(calendar_url)
    ini['meterLink']['tooltiptext'] = calendar_url

    keep_url = 'https://keep.google.com/u/0/#home'
    ini['meterLink_google_keep']['Meter'] = 'String'
    ini['meterLink_google_keep']['MeterStyle'] = 'sItemLink'
    ini['meterLink_google_keep']['X'] = '(58*#Scale#)'
    ini['meterLink_google_keep']['Y'] = '(38*#Scale#)'
    ini['meterLink_google_keep']['W'] = '60'
    ini['meterLink_google_keep']['H'] = '55'
    ini['meterLink_google_keep']['Text'] = '|Keep'
    ini['meterLink_google_keep']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(keep_url)
    ini['meterLink_google_keep']['tooltiptext'] = keep_url

    #  endregion

    # region Render dimensions
    width_multiplier = 1.7
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'

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

    # region Build Dump
    line_ctr = 2
    separator_count = 48
    dump = '{0}\nCURRENT TIME BLOCKS ENDS\n'.format(make_separator(separator_count))
    for event_now in events_today_now:
        line_ctr += 1
        end_time = datetime.fromisoformat(event_now['end']['dateTime']).strftime('%I:%M %p')
        dump += '> {0:<35} {1:>10}\n'.format(event_now['calendarSummary'], end_time)

    dump += '{0}\nUPCOMING TIME BLOCKS STARTS\n'.format(make_separator(separator_count))
    for event_upcoming in events_today_upcoming:
        line_ctr += 1
        end_time = datetime.fromisoformat(event_upcoming['start']['dateTime']).strftime('%I:%M %p')
        dump += '> {0:<35} {1:>10}\n'.format(event_upcoming['calendarSummary'], end_time)

    dump += make_separator(separator_count) + '\n'

    if len(events_today_now) == 0:
        line_ctr = 5
        dump = 'No events. \nYou should be sleeping now...\n\n\n'
    for event_now in events_today_now:
        dump += "{0}\n".format(event_now['calendarSummary'])
        match = 0
        line_ctr += 1
        for all_day_event in events_today_filtered:
            if event_now['calendarSummary'] == all_day_event['calendarSummary']:
                line_ctr += 1
                match = 1
                dump += '* {0:<20}\n'.format(all_day_event['summary'])
        if match == 0:
            dump += 'No events.\n\n'
        dump += "{0}\n".format(make_separator(separator_count))
    # endregion

    ini['Variables']['ItemLines'] = '{0}'.format(line_ctr)

    return dump

