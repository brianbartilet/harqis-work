from datetime import datetime

from core.apps.sprout.app.celery import SPROUT
from core.utilities.data.qlist import QList
from core.utilities.data.strings import make_separator

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_config

from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents, EventType
from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER


_sections__account_calendar = {
    "meterLink_google_keep": {
        "Preset": "InjectedByTest",
    }
}

@SPROUT.task()
@init_config(RAINMETER_CONFIG,
             hud_item_name='CALENDAR PEEK',
             new_sections_dict=_sections__account_calendar,
             play_sound=True)
def show_calendar_information(cfg_id__gsuite, ini=ConfigHelperRainmeter()):

    cfg__gsuite= CONFIG_MANAGER.get(cfg_id__gsuite)
    service = ApiServiceGoogleCalendarEvents(cfg__gsuite)
    events_today_all_day = service.get_all_events_today(EventType.ALL_DAY)
    events_today_now = service.get_all_events_today(EventType.NOW)

    events_today_filtered = []
    for event in events_today_all_day:
        for current_block in events_today_now:
            if event['calendarSummary'] == current_block['calendarSummary']:
                events_today_filtered.append(event)
            else:
                continue

    calendar_url = "https://calendar.google.com/calendar/u/0/r"
    ini['meterLink']['text'] = "Calendar"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(calendar_url)
    ini['meterLink']['tooltiptext'] = calendar_url

    #  region Section: meterLink_calendar
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

    # region Render meter
    width_multiplier = 1.7
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

    line_ctr = 0
    dump = '{0}\nCURRENT TIME BLOCKS ENDS\n'.format(make_separator(48))
    for event_now in events_today_now:
        end_time = datetime.fromisoformat(event_now['end']['dateTime']).strftime('%I:%M %p')
        dump = dump + '> {0:>5} {1:>14}\n'.format(event_now['calendarSummary'], end_time)
    if len(events_today_now) == 0:
        line_ctr += 1
        dump = dump + 'No events. \nYou should be sleeping now...\n\n\n'
    dump = dump + make_separator(48) + '\n'

    for event_now in events_today_now:
        dump = dump + "{0}\n".format(event_now['calendarSummary'])
        for all_day_event in events_today_filtered:
            line_ctr += 1
            if event_now['calendarSummary'] == all_day_event['calendarSummary']:
                dump = dump + '* {0:<20}\n'.format(all_day_event['summary'])
        dump = dump + "{0}\n".format(make_separator(48))

    ini['Variables']['ItemLines'] = '{0}'.format(line_ctr)


    return dump

