from typing import List, Optional, Dict

from apps.notion.references.web.base_api_service import BaseApiServiceNotion
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceNotionBlocks(BaseApiServiceNotion):
    """
    Notion REST API — block operations.

    Methods:
        get_block()             → Retrieve a block by ID
        get_block_children()    → List all children of a block (page or block)
        append_block_children() → Append new blocks to a parent block or page
        update_block()          → Update a block's content
        delete_block()          → Archive (delete) a block
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceNotionBlocks, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_block(self, block_id: str):
        """
        Retrieve a single block by its ID.

        Args:
            block_id: The block's UUID (with or without dashes).
        """
        self.request.get() \
            .add_uri_parameter('blocks') \
            .add_uri_parameter(block_id)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_block_children(self, block_id: str, start_cursor: str = None,
                           page_size: int = 100):
        """
        Retrieve all child blocks of a block or page.

        Args:
            block_id:     The parent block or page UUID.
            start_cursor: Pagination cursor from previous response.
            page_size:    Number of results per page (max 100, default 100).
        """
        self.request.get() \
            .add_uri_parameter('blocks') \
            .add_uri_parameter(block_id) \
            .add_uri_parameter('children') \
            .add_query_string('page_size', str(page_size))

        if start_cursor:
            self.request.add_query_string('start_cursor', start_cursor)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def append_block_children(self, block_id: str, children: List[Dict]):
        """
        Append new child blocks to a parent block or page.

        Args:
            block_id: Parent block or page UUID.
            children: List of block objects to append.

        Example block objects:
            # Paragraph
            {'object': 'block', 'type': 'paragraph',
             'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': 'Hello'}}]}}

            # Heading 1
            {'object': 'block', 'type': 'heading_1',
             'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': 'Title'}}]}}

            # To-do
            {'object': 'block', 'type': 'to_do',
             'to_do': {'rich_text': [{'type': 'text', 'text': {'content': 'Task'}}],
                       'checked': False}}
        """
        self.request.patch() \
            .add_uri_parameter('blocks') \
            .add_uri_parameter(block_id) \
            .add_uri_parameter('children') \
            .add_json_payload({'children': children})

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_block(self, block_id: str, block_type: str, content: Dict):
        """
        Update a block's content.

        Args:
            block_id:   The block's UUID.
            block_type: Block type string (e.g. 'paragraph', 'heading_1', 'to_do').
            content:    Block type-specific content dict.

        Example:
            update_block(block_id, 'paragraph',
                         {'rich_text': [{'type': 'text', 'text': {'content': 'Updated'}}]})
        """
        self.request.patch() \
            .add_uri_parameter('blocks') \
            .add_uri_parameter(block_id) \
            .add_json_payload({block_type: content})

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def delete_block(self, block_id: str):
        """
        Archive (soft-delete) a block.

        Args:
            block_id: The block's UUID.
        """
        self.request.patch() \
            .add_uri_parameter('blocks') \
            .add_uri_parameter(block_id) \
            .add_json_payload({'archived': True})

        return self.client.execute_request(self.request.build())
