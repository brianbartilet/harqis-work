import os
from typing import Optional

from apps.antropic.references.dto.file import DtoAnthropicFile
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic


class ApiServiceAnthropicFiles(BaseApiServiceAnthropic):
    """
    Service for interacting with the Anthropic Files API (beta).

    Supports uploading, listing, retrieving metadata, and deleting files.
    Files can be referenced in Messages API calls to avoid re-sending large content.

    Beta header: files-api-2025-04-14
    """

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @staticmethod
    def _parse_file(response) -> DtoAnthropicFile:
        return DtoAnthropicFile(
            id=getattr(response, 'id', None),
            created_at=str(getattr(response, 'created_at', '') or ''),
            filename=getattr(response, 'filename', None),
            mime_type=getattr(response, 'mime_type', None),
            size_bytes=getattr(response, 'size', None),
            type=getattr(response, 'type', 'file'),
            downloadable=getattr(response, 'downloadable', None),
        )

    def upload_file(self, file_path: str, mime_type: Optional[str] = None) -> DtoAnthropicFile:
        """
        Upload a file to Anthropic for use in subsequent API calls.

        Args:
            file_path: Absolute or relative path to the file to upload.
            mime_type: MIME type override. Defaults to 'application/octet-stream'.

        Returns:
            DtoAnthropicFile with the created file's metadata.
        """
        filename = os.path.basename(file_path)
        resolved_mime = mime_type or 'application/octet-stream'

        with open(file_path, 'rb') as f:
            response = self.base_client.beta.files.upload(
                file=(filename, f, resolved_mime),
            )

        return self._parse_file(response)

    def list_files(self) -> list[DtoAnthropicFile]:
        """
        List all uploaded files for the current API key.

        Returns:
            List of DtoAnthropicFile objects.
        """
        response = self.base_client.beta.files.list()
        return [self._parse_file(f) for f in response.data]

    def retrieve_file_metadata(self, file_id: str) -> DtoAnthropicFile:
        """
        Retrieve metadata for a specific uploaded file.

        Args:
            file_id: The unique file identifier returned at upload time.

        Returns:
            DtoAnthropicFile with the file's metadata.
        """
        response = self.base_client.beta.files.retrieve_metadata(file_id)
        return self._parse_file(response)

    def delete_file(self, file_id: str) -> dict:
        """
        Delete an uploaded file by ID.

        Args:
            file_id: The unique file identifier to delete.

        Returns:
            Deletion confirmation response as dict.
        """
        response = self.base_client.beta.files.delete(file_id)
        return vars(response) if hasattr(response, '__dict__') else {'id': file_id}
