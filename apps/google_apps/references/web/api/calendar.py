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
            return "dateTime" in event.get("start", {})

        def extract_event_bounds(event, tz):
            start_raw = event["start"]

            # NEW — exclude all-day events entirely for NOW
            if "dateTime" not in start_raw:
                return None, None

            end_raw = event.get("end", {})
            start = datetime.fromisoformat(start_raw["dateTime"])
            end = datetime.fromisoformat(end_raw["dateTime"])
            return start, end

        def is_happening_now(event, now_dt, tz):
            start, end = extract_event_bounds(event, tz)

            if start is None:  # All-day event — skip
                return False

            return start <= now_dt < end

        all_events = []

        cal_list = self.service.calendarList().list().execute()
        calendars = cal_list.get("items", [])

        for cal in calendars:
            cal_id = cal["id"]
            cal_tz = cal.get("timeZone", "UTC")
            tz = ZoneInfo(cal_tz)

            now = datetime.now(tz)

            start = datetime(now.year, now.month, now.day, tzinfo=tz)
            end = start + timedelta(days=1)

            resp = self.service.events().list(
                calendarId=cal_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
                timeZone=cal_tz,
            ).execute()

            events = resp.get("items", [])

            for e in events:
                e["calendarId"] = cal_id
                e["calendarSummary"] = cal.get("summary", "")

                if event_type == EventType.ALL_DAY and not is_all_day(e):
                    continue

                if event_type == EventType.SCHEDULED and not is_scheduled(e):
                    continue

                if event_type == EventType.NOW and not is_happening_now(e, now, tz):
                    continue

                all_events.append(e)

        return all_events
