from apps.google_apps.references.web.base_api_service import BaseApiServiceGoogle
from apiclient import discovery

from enum import Enum
from typing import Type, TypeVar
T = TypeVar('T')


class SheetInputOption(Enum):
    USER_ENTERED = 'USER_ENTERED'
    RAW = 'RAW'


class ApiServiceGoogleSheets(BaseApiServiceGoogle):

    def __init__(self, config, scopes_list):
        super(ApiServiceGoogleSheets, self).__init__(config, scopes_list=scopes_list)
        self.row_data = []
        self.data = {
            'values': self.row_data
        }
        self.sheet_id = self.config.app_data['sheet_id']

    def __new__(cls, kls: Type[T] = discovery.Resource, *args, **kwargs) -> T:
        obj = BaseApiServiceGoogle(*args, **kwargs)
        creds = obj.client.authorize()

        cls.workbook = discovery.build('sheets', 'v4', http=creds).spreadsheets()

        return super(ApiServiceGoogleSheets, cls).__new__(cls, *args, **kwargs)

    def set_headers(self, headers, row_index=0):
        self.row_data.insert(row_index, headers)

    def set_row_data(self, data, sort_index=None, reverse=False):

        if sort_index is not None:
            data = sorted(data, key=lambda x: x[sort_index], reverse=reverse)

        for item in data:
            self.row_data.append(item)

    def update_sheet_data(self, range_expression='Sheet1!A1', value_input_option=SheetInputOption.USER_ENTERED.value):

        self.workbook.values()\
            .update(spreadsheetId=self.sheet_id,
                    range=range_expression,
                    body=self.data,
                    valueInputOption=value_input_option)\
            .execute()

    def get_sheet_data(self, range_expression='Sheet1!A1'):
        return self.workbook.values()\
            .get(spreadsheetId=self.sheet_id, range=range_expression)\
            .execute().get('values', [])

    def clear_sheet_data(self, range_expression='Sheet1!A1'):
        return self.workbook.values()\
            .clear(spreadsheetId=self.sheet_id, range=range_expression)\
            .execute()

