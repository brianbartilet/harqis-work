from typing import List, Optional, Dict, Any

from apps.notion.references.web.base_api_service import BaseApiServiceNotion
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceNotionPages(BaseApiServiceNotion):
    """
    Notion REST API — page operations.

    Methods:
        get_page()              → Retrieve a page by ID
        get_page_property()     → Retrieve a single page property value
        create_page()           → Create a page in a database or as a child of another page
        update_page()           → Update page properties or archive/unarchive
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceNotionPages, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_page(self, page_id: str):
        """
        Retrieve a page by its ID.

        Args:
            page_id: The page's UUID (with or without dashes).
        """
        self.request.get() \
            .add_uri_parameter('pages') \
            .add_uri_parameter(page_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_page_property(self, page_id: str, property_id: str):
        """
        Retrieve a single property value from a page.

        Args:
            page_id:     The page's UUID.
            property_id: The property's ID (from the database schema).
        """
        self.request.get() \
            .add_uri_parameter('pages') \
            .add_uri_parameter(page_id) \
            .add_uri_parameter('properties') \
            .add_uri_parameter(property_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_page(self, parent: Dict, properties: Dict,
                    children: List[Dict] = None, icon: Dict = None,
                    cover: Dict = None):
        """
        Create a new page in a database or as a child of another page.

        Args:
            parent:     Parent object, e.g. {'database_id': '<id>'} or {'page_id': '<id>'}.
            properties: Property values dict matching the parent database schema.
            children:   Optional list of block objects to add as page content.
            icon:       Optional icon object (emoji or external URL).
            cover:      Optional cover image object (external URL).

        Examples:
            # Create a page in a database
            create_page(
                parent={'database_id': 'abc123'},
                properties={'Name': {'title': [{'text': {'content': 'My task'}}]}}
            )

            # Create a sub-page
            create_page(
                parent={'page_id': 'abc123'},
                properties={'title': [{'text': {'content': 'Sub-page'}}]}
            )
        """
        payload: Dict[str, Any] = {
            'parent': parent,
            'properties': properties,
        }
        if children:
            payload['children'] = children
        if icon:
            payload['icon'] = icon
        if cover:
            payload['cover'] = cover

        self.request.post() \
            .add_uri_parameter('pages') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_page(self, page_id: str, properties: Dict = None,
                    archived: bool = None, icon: Dict = None,
                    cover: Dict = None):
        """
        Update a page's properties or archive/unarchive it.

        Args:
            page_id:    The page's UUID.
            properties: Updated property values (optional).
            archived:   True to archive the page, False to unarchive (optional).
            icon:       Updated icon object (optional).
            cover:      Updated cover object (optional).
        """
        payload: Dict[str, Any] = {}
        if properties is not None:
            payload['properties'] = properties
        if archived is not None:
            payload['archived'] = archived
        if icon is not None:
            payload['icon'] = icon
        if cover is not None:
            payload['cover'] = cover

        self.request.patch() \
            .add_uri_parameter('pages') \
            .add_uri_parameter(page_id) \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())
