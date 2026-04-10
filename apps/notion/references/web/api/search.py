from typing import Optional, Dict, List

from apps.notion.references.web.base_api_service import BaseApiServiceNotion
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceNotionSearch(BaseApiServiceNotion):
    """
    Notion REST API — search operations.

    Methods:
        search()    → Search all pages and databases accessible to the integration
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceNotionSearch, self).__init__(config, **kwargs)

    @deserialized(dict)
    def search(self, query: str = None, filter_object: str = None,
               sort_direction: str = 'descending', sort_timestamp: str = 'last_edited_time',
               start_cursor: str = None, page_size: int = 100):
        """
        Search all pages and databases accessible to the integration.

        Args:
            query:          Plain-text search query. Returns all results if omitted.
            filter_object:  Limit results to 'page' or 'database' (optional).
            sort_direction: 'ascending' or 'descending' (default: 'descending').
            sort_timestamp: Field to sort by. Only 'last_edited_time' is supported.
            start_cursor:   Pagination cursor from previous response.
            page_size:      Number of results per page (max 100, default 100).
        """
        payload: Dict = {
            'sort': {
                'direction': sort_direction,
                'timestamp': sort_timestamp,
            },
            'page_size': page_size,
        }
        if query:
            payload['query'] = query
        if filter_object:
            payload['filter'] = {'value': filter_object, 'property': 'object'}
        if start_cursor:
            payload['start_cursor'] = start_cursor

        self.request.post() \
            .add_uri_parameter('search') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())
