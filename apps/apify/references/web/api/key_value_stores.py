"""
Key-Value Stores — arbitrary key/value records produced by an actor run.

Reference: https://docs.apify.com/api/v2#tag/Key-value-stores
"""
from typing import Optional, Any

from apps.apify.references.web.base_api_service import BaseApiServiceApify
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceApifyKeyValueStores(BaseApiServiceApify):
    """
    Read records from key-value stores. Useful for actors that emit binary
    output (PDFs, screenshots, JSON manifests) outside the dataset.

    Methods:
        list_stores()    → Account-wide list
        get_store()      → Single store metadata
        list_keys()      → Keys within a store
        get_record()     → One record's value (raw)
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceApifyKeyValueStores, self).__init__(config, **kwargs)

    @deserialized(dict)
    def list_stores(self, unnamed: bool = False, limit: Optional[int] = None,
                    offset: Optional[int] = None) -> dict:
        """List stores. ``unnamed=True`` includes auto-created per-run stores."""
        self.request.get().add_uri_parameter('key-value-stores')
        if unnamed:
            self.request.add_query_string('unnamed', 'true')
        if limit is not None:
            self.request.add_query_string('limit', limit)
        if offset is not None:
            self.request.add_query_string('offset', offset)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_store(self, store_id: str) -> dict:
        """Get store metadata."""
        self.request.get().add_uri_parameter(f'key-value-stores/{store_id}')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_keys(self, store_id: str, exclusive_start_key: Optional[str] = None,
                  limit: Optional[int] = None) -> dict:
        """List keys within a store. Use ``exclusive_start_key`` for pagination."""
        self.request.get().add_uri_parameter(f'key-value-stores/{store_id}/keys')
        if exclusive_start_key:
            self.request.add_query_string('exclusiveStartKey', exclusive_start_key)
        if limit is not None:
            self.request.add_query_string('limit', limit)
        return self.client.execute_request(self.request.build())

    def get_record(self, store_id: str, key: str) -> Any:
        """
        Fetch a single record's raw value.

        The Content-Type is preserved — JSON keys deserialize automatically,
        binary keys come back as bytes/str depending on the framework's
        response handling.
        """
        self.request.get().add_uri_parameter(f'key-value-stores/{store_id}/records/{key}')
        return self.client.execute_request(self.request.build())
