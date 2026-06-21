import os
import time

import ijson

from apps.scryfall.references.web.base_api_service import BaseApiServiceAppScryfallMtg

from core.utilities.logging.custom_logger import logger as log
from core.web.services.core.decorators.deserializer import deserialized
from core.utilities.resources.download_file import ServiceDownloadFile

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
                url = response['download_uri']
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

        Streams the bulk JSON array with ijson so the multi-GB file is never fully
        loaded into memory. Matching is a case-insensitive substring on ``field``.

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
        url = info['download_uri']
        filename = url.split('/')[-1]
        folder = self.config.app_data['path_folder_static_file']
        file_path = os.path.join(folder, filename)

        if force_download or not os.path.exists(file_path):
            downloader = ServiceDownloadFile(url=url)
            downloader.download_file(filename, folder)
            log.warning(f"Bulk file downloaded: {file_path}")

        needle = query.lower()
        results = []
        with open(file_path, 'rb') as fh:
            for card in ijson.items(fh, 'item'):
                value = card.get(field)
                if value is not None and needle in str(value).lower():
                    results.append(card)
                    if len(results) >= limit:
                        break

        log.warning(f"query_bulk matched {len(results)} card(s) for '{query}' in '{field}'")
        return results