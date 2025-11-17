import time

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