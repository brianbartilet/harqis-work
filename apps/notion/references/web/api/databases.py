from typing import List, Optional, Dict, Any

from apps.notion.references.web.base_api_service import BaseApiServiceNotion
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceNotionDatabases(BaseApiServiceNotion):
    """
    Notion REST API — database operations.

    Methods:
        get_database()      → Retrieve a database by ID
        query_database()    → Query pages in a database with optional filters
        create_database()   → Create a new database as a child of a page
        update_database()   → Update database title or properties
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceNotionDatabases, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_database(self, database_id: str):
        """
        Retrieve a database by its ID.

        Args:
            database_id: The database's UUID (with or without dashes).
        """
        self.request.get() \
            .add_uri_parameter('databases') \
            .add_uri_parameter(database_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def query_database(self, database_id: str, filter: Dict = None,
                       sorts: List[Dict] = None, start_cursor: str = None,
                       page_size: int = 100):
        """
        Query all pages in a database, with optional filter and sort.

        Args:
            database_id:  The database's UUID.
            filter:       Notion filter object (see API docs).
            sorts:        List of sort objects (see API docs).
            start_cursor: Cursor for pagination (from previous response's next_cursor).
            page_size:    Number of results per page (max 100, default 100).
        """
        payload: Dict[str, Any] = {'page_size': page_size}
        if filter:
            payload['filter'] = filter
        if sorts:
            payload['sorts'] = sorts
        if start_cursor:
            payload['start_cursor'] = start_cursor

        self.request.post() \
            .add_uri_parameter('databases') \
            .add_uri_parameter(database_id) \
            .add_uri_parameter('query') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_database(self, parent_page_id: str, title: str,
                        properties: Dict = None):
        """
        Create a new inline database as a child of a page.

        Args:
            parent_page_id: UUID of the parent page.
            title:          Database title (plain text).
            properties:     Property schema dict. Defaults to a single 'Name' title property.
        """
        if properties is None:
            properties = {'Name': {'title': {}}}

        payload = {
            'parent': {'type': 'page_id', 'page_id': parent_page_id},
            'title': [{'type': 'text', 'text': {'content': title}}],
            'properties': properties,
            'is_inline': True,
        }

        self.request.post() \
            .add_uri_parameter('databases') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_database(self, database_id: str, title: str = None,
                        properties: Dict = None):
        """
        Update a database's title or property schema.

        Args:
            database_id: The database's UUID.
            title:       New plain-text title (optional).
            properties:  Updated property schema dict (optional).
        """
        payload: Dict[str, Any] = {}
        if title is not None:
            payload['title'] = [{'type': 'text', 'text': {'content': title}}]
        if properties is not None:
            payload['properties'] = properties

        self.request.patch() \
            .add_uri_parameter('databases') \
            .add_uri_parameter(database_id) \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())
