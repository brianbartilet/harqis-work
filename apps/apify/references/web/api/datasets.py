"""
Datasets — read items produced by finished actor runs.

Reference: https://docs.apify.com/api/v2#tag/Datasets
"""
from typing import Optional, List, Any

from apps.apify.references.web.base_api_service import BaseApiServiceApify
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceApifyDatasets(BaseApiServiceApify):
    """
    Read-only dataset access.

    Methods:
        list_datasets()      → All datasets in the account
        get_dataset()        → Metadata for one dataset
        get_dataset_items()  → The records themselves (paginated)
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceApifyDatasets, self).__init__(config, **kwargs)

    @deserialized(dict)
    def list_datasets(self, unnamed: bool = False, limit: Optional[int] = None,
                      offset: Optional[int] = None, desc: bool = True) -> dict:
        """
        List datasets in the account.

        Args:
            unnamed: Include the auto-generated default datasets created per run.
            limit:   Max datasets to return.
            offset:  Pagination offset.
            desc:    Newest first if True.
        """
        self.request.get().add_uri_parameter('datasets')
        if unnamed:
            self.request.add_query_string('unnamed', 'true')
        if limit is not None:
            self.request.add_query_string('limit', limit)
        if offset is not None:
            self.request.add_query_string('offset', offset)
        if desc:
            self.request.add_query_string('desc', 'true')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_dataset(self, dataset_id: str) -> dict:
        """Get dataset metadata (item count, sizes, owner) without the items."""
        self.request.get().add_uri_parameter(f'datasets/{dataset_id}')
        return self.client.execute_request(self.request.build())

    @deserialized(list)
    def get_dataset_items(self, dataset_id: str, fmt: str = 'json', clean: bool = True,
                          limit: Optional[int] = None, offset: Optional[int] = None,
                          desc: bool = False, fields: Optional[List[str]] = None,
                          omit: Optional[List[str]] = None) -> Any:
        """
        Fetch dataset records.

        Args:
            dataset_id: ID returned from a finished run (``defaultDatasetId``).
            fmt:        'json' | 'jsonl' | 'csv' | 'xml' | 'html' | 'rss'.
            clean:      Drop hidden/empty fields.
            limit:      Max items.
            offset:     Pagination offset.
            desc:       Reverse order.
            fields:     Whitelist of fields to keep.
            omit:       Blacklist of fields to drop.
        """
        self.request.get().add_uri_parameter(f'datasets/{dataset_id}/items')
        self.request.add_query_string('format', fmt)
        if clean:
            self.request.add_query_string('clean', 'true')
        if limit is not None:
            self.request.add_query_string('limit', limit)
        if offset is not None:
            self.request.add_query_string('offset', offset)
        if desc:
            self.request.add_query_string('desc', 'true')
        if fields:
            self.request.add_query_string('fields', ','.join(fields))
        if omit:
            self.request.add_query_string('omit', ','.join(omit))
        return self.client.execute_request(self.request.build())
