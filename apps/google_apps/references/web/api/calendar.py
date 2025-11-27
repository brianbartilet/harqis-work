from __future__ import annotations

import functools
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from enum import Enum, auto

from apps.google_apps.references.web.base_api_service import BaseApiServiceGoogle
from apps.google_apps.config import CONFIG

from core.utilities.data.qlist import QList
from core.utilities.logging.custom_logger import logger as log
from core.web.services.core.decorators.deserializer import deserialized

from apps.google_apps.references.web.discovery import BaseGoogleDiscoveryService


class EventType(Enum):
    ALL = auto()
    ALL_DAY = auto()
    NOW = auto()
    SCHEDULED = auto()
    UPCOMING_UNTIL_EOD = auto()


def holidays_aware(country_code='en.philippines'):

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            klass_get_holidays = ApiServiceGoogleCalendar(CONFIG)
            data = klass_get_holidays.get_holidays(country_code=country_code)
            today = datetime.today().strftime('%Y-%m-%d')
            try:
                exists = QList(data).where(lambda x: x['start']['date'] == today)
                if len(exists) == 0:
                    return func(*args, **kwargs)
                else:
                    holiday = exists.first()['summary']
                    log.warning("Job skipped due to holidays in: '{0}' {1}: {2}"
                                .format(country_code, holiday, func.__name__))
                    return None
            except TypeError:
                log.error("Invalid country code: '{0}'".format(country_code))
                raise TypeError

        return wrapper

    return decorator


class ApiServiceGoogleCalendar(BaseApiServiceGoogle):

    def __init__(self, config, **kwargs):
        super(ApiServiceGoogleCalendar, self).__init__(config, use_gclient=False, **kwargs)
        self.initialize()

    def initialize(self):
        self.request.set_base_uri('calendar/v3')

    @deserialized(dict, child='items')
    def get_holidays(self, country_code='en.philippines'):
        self.request.get() \
            .add_uri_parameter('calendars/{0}%23holiday%40group.v.calendar.google.com/events'.format(country_code))\
            .add_query_string('key', self.config.app_data['api_key'])

        response =  self.client.execute_request(self.request.build())

        return response


class ApiServiceGoogleCalendarEvents(BaseGoogleDiscoveryService):
    """
    Google Calendar events service using the discovery API.

    Provides:
        - list_events(...) for generic event queries
        - get_todays_events(...) convenience wrapper
    """

    SERVICE_NAME = "calendar"
    SERVICE_VERSION = "v3"

    def __init__(self, config, calendar_id: str = "primary", **kwargs,) -> None:
        super().__init__(config, **kwargs)
        self.calendar_id = calendar_id
        self.events_resource = self.service.events()

    def list_events(
        self,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 2500,
        single_events: bool = True,
        order_by: str = "startTime",
        **extra_query: Any,
    ) -> Dict[str, Any]:
        """
        Wraps calendar.events().list

        Args:
            time_min: RFC3339 timestamp string (inclusive), e.g. '2025-11-21T00:00:00Z'
            time_max: RFC3339 timestamp string (exclusive)
            max_results: max events returned
            single_events: expand recurring events if True
            order_by: usually 'startTime'
            extra_query: any extra parameters to pass (q, timeZone, etc.)

        Returns:
            Full API response dict from events().list().execute()
        """
        params: Dict[str, Any] = {
            "calendarId": self.calendar_id,
            "maxResults": max_results,
            "singleEvents": single_events,
            "orderBy": order_by,
        }

        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max

        params.update(extra_query)

        return self.events_resource.list(**params).execute()

    def get_all_events_today(
            self,
            event_type: EventType = EventType.ALL,
            max_results: int = 2500,
    ):
        def is_all_day(event):
            return (
                    "date" in event.get("start", {})
                    and "dateTime" not in event.get("start", {})
            )

        def is_scheduled(event):
            # scheduled == has a dateTime start (not all-day)
            return "dateTime" in event.get("start", {})

        def extract_event_bounds(event, tz):
            start_raw = event.get("start", {})

            # Exclude all-day events from time-based checks
            if "dateTime" not in start_raw:
                return None, None

            end_raw = event.get("end", {})
            start = datetime.fromisoformat(start_raw["dateTime"])
            end = datetime.fromisoformat(end_raw["dateTime"])
            return start, end

        def is_happening_now(event, now_dt, tz):
            start, end = extract_event_bounds(event, tz)
            if start is None:  # All-day or invalid -> skip for NOW
                return False
            return start <= now_dt < end

        def is_upcoming_scheduled(event, now_dt, tz):
            if not is_scheduled(event):
                return False
            start, _ = extract_event_bounds(event, tz)
            if start is None:
                return False
            # only events starting at or after "now"
            return start >= now_dt

        def is_upcoming_scheduled_eod(event, now_dt, tz):
            if not is_scheduled(event):
                return False

            start, end = extract_event_bounds(event, tz)
            if start is None:
                return False

            # Define end of the current day in the event's timezone
            end_of_day = datetime(
                now_dt.year, now_dt.month, now_dt.day, 23, 59, 59, tzinfo=tz
            )

            # Must start after now
            if start < now_dt:
                return False

            # Must start before midnight AND end before midnight
            if start > end_of_day:
                return False

            if end > end_of_day:
                return False

            return True

        all_events = []

        cal_list = self.service.calendarList().list().execute()
        calendars = cal_list.get("items", [])

        for cal in calendars:
            cal_id = cal["id"]
            cal_tz = cal.get("timeZone", "UTC")
            tz = ZoneInfo(cal_tz)

            now = datetime.now(tz)
            start_of_day = datetime(now.year, now.month, now.day, tzinfo=tz)
            end_of_day = start_of_day + timedelta(days=1)

            # For SCHEDULED and NOW we only need from "now" to end-of-day;
            # for ALL / ALL_DAY we keep the full day.
            if event_type in (EventType.SCHEDULED, EventType.NOW):
                time_min = now
            else:
                time_min = start_of_day

            time_max = end_of_day

            resp = self.service.events().list(
                calendarId=cal_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
                timeZone=cal_tz,
            ).execute()

            events = resp.get("items", [])

            for e in events:
                e["calendarId"] = cal_id
                e["calendarSummary"] = cal.get("summary", "")

                if event_type == EventType.ALL_DAY:
                    if not is_all_day(e):
                        continue

                elif event_type == EventType.SCHEDULED:
                    # upcoming, non all-day, from now to end-of-day
                    if not is_upcoming_scheduled(e, now, tz):
                        continue

                elif event_type == EventType.NOW:
                    if not is_happening_now(e, now, tz):
                        continue

                elif event_type == EventType.UPCOMING_UNTIL_EOD:
                    if not is_upcoming_scheduled_eod(e, now, tz):
                        continue

                # EventType.ALL falls through with no extra filtering
                all_events.append(e)

        return all_events
