from apps.google_apps.references.web.base_api_service import BaseApiServiceGoogle
from apps.google_apps.config import CONFIG

from core.utilities.data.qlist import QList
from core.utilities.logging.custom_logger import logger as log
from core.web.services.core.decorators.deserializer import deserialized

from datetime import datetime
import functools


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
        self.request.set_base_uri('calendar/v3/calendars')

    @deserialized(dict, child='items')
    def get_holidays(self, country_code='en.philippines'):
        self.request.get() \
            .add_uri_parameter('{0}%23holiday%40group.v.calendar.google.com/events'.format(country_code))\
            .add_query_string('key', self.config.app_data['api_key'])

        response =  self.client.execute_request(self.request.build())

        return response
