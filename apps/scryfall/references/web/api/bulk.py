import gzip
import json
import os
import time
from pathlib import Path

import ijson

from apps.scryfall.references.web.base_api_service import BaseApiServiceAppScryfallMtg

from core.utilities.logging.custom_logger import logger as log
from core.web.services.core.decorators.deserializer import deserialized
from core.utilities.resources.download_file import ServiceDownloadFile


def _bulk_download_uri(info: dict | list[dict]) -> str:
    """Return the current Scryfall bulk URI, with legacy API compatibility."""
    if not isinstance(info, dict):
        raise RuntimeError(
            "Scryfall bulk metadata did not include a download URI "
            f"(response type: {type(info).__name__})"
        )
    url = info.get('jsonl_download_uri') or info.get('download_uri')
    if not isinstance(url, str) or not url:
        raise RuntimeError(
            "Scryfall bulk metadata did not include a download URI "
            f"(response keys: {sorted(info)})"
        )
    return url


def iter_bulk_cards(file_path):
    """Stream cards from current JSONL gzip files or legacy JSON arrays."""
    path = Path(file_path)
    if path.name.endswith('.jsonl.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
        return

    if path.name.endswith('.jsonl'):
        with path.open('r', encoding='utf-8') as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
        return

    with path.open('rb') as fh:
        yield from ijson.items(fh, 'item')


class ApiServiceScryfallBulkData(BaseApiServiceAppScryfallMtg):

    def __init__(self, config, **kwargs):
        super(ApiServiceScryfallBulkData, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request \
            .set_base_uri('bulk-data')

    @deserialized(dict)
    def get_card_data_bulk(self, bulk_data_type: str = "all-cards"):
        self.request.get() \
            .add_uri_parameter(bulk_data_type) \
            .add_query_string('format', 'json') \
            .add_query_string('pretty', 'true')

        response = self.client.execute_request(self.request.build(), rate_limit_delay=10)

        return response

    def download_bulk_file(self, bulk_data_type: str = "all-cards", max_retries=10, retry_delay=30):

        for attempt in range(1, max_retries + 1):
            try:
                response = self.get_card_data_bulk(bulk_data_type)
                url = _bulk_download_uri(response)
                filename = url.split('/')[-1]
                downloader = ServiceDownloadFile(url=url)
                downloader.download_file(filename, self.config.app_data['path_folder_static_file'])
                log.warning(f"Download completed for attempt {attempt}")
                break
            except Exception as e:
                if attempt == max_retries:
                    log.error(f"Failed after {max_retries} retries: {e}")
                    raise
                log.warning(
                    f"Retry {attempt}/{max_retries} failed: {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                time.sleep(retry_delay)

    def query_bulk(self, query: str, bulk_data_type: str = "default-cards",
                   field: str = "name", limit: int = 50, force_download: bool = False):
        """Download (or reuse) the latest bulk file and return only matching cards.

        Streams the compressed JSONL (or a legacy JSON array) so the bulk file is
        never fully loaded into memory. Matching is a case-insensitive substring.

        Args:
            query: Substring to match against ``field``.
            bulk_data_type: Scryfall bulk type (default ``default-cards``; ``all-cards`` is far larger).
            field: Card field to match against (default ``name``).
            limit: Maximum number of cards to return.
            force_download: Re-download even if the current day's file already exists.

        Returns:
            A list of matching card dicts (at most ``limit``).
        """
        info = self.get_card_data_bulk(bulk_data_type)
        url = _bulk_download_uri(info)
        filename = url.split('/')[-1]
        folder = self.config.app_data['path_folder_static_file']
        file_path = os.path.join(folder, filename)

        if force_download or not os.path.exists(file_path):
            downloader = ServiceDownloadFile(url=url)
            downloader.download_file(filename, folder)
            log.warning(f"Bulk file downloaded: {file_path}")

        needle = query.lower()
        results = []
        for card in iter_bulk_cards(file_path):
            value = card.get(field)
            if value is not None and needle in str(value).lower():
                results.append(card)
                if len(results) >= limit:
                    break

        log.warning(f"query_bulk matched {len(results)} card(s) for '{query}' in '{field}'")
        return results
