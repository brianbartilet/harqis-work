from typing import List, Optional

from apps.orgo.references.web.base_api_service import BaseApiServiceOrgo
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOrgoFiles(BaseApiServiceOrgo):
    """
    Orgo AI API — file management.

    Transfer files between the local caller and cloud computers.

    Methods:
        list_files()        → List files for a workspace/computer
        download_file()     → Get a temporary download URL for a file
        delete_file()       → Delete a file by ID
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceOrgoFiles, self).__init__(config, **kwargs)

    @deserialized(List[dict])
    def list_files(self, workspace_id: str, computer_id: Optional[str] = None):
        """
        List files associated with a workspace, optionally filtered by computer.

        Args:
            workspace_id: UUID of the workspace.
            computer_id:  Optional computer ID to filter results.
        """
        self.request.get().add_uri_parameter('files')
        self.request.add_query_string('projectId', workspace_id)
        if computer_id:
            self.request.add_query_string('desktopId', computer_id)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def download_file(self, file_id: str):
        """
        Get a temporary download URL for a file (expires in 1 hour).

        Args:
            file_id: File ID returned from list_files or upload.

        Returns:
            Dict with download URL.
        """
        self.request.get() \
            .add_uri_parameter('files') \
            .add_uri_parameter('download') \
            .add_query_string('id', file_id)
        return self.client.execute_request(self.request.build())

    def delete_file(self, file_id: str):
        """
        Delete a file by ID.

        Args:
            file_id: File ID to delete.
        """
        self.request.delete() \
            .add_uri_parameter('files') \
            .add_uri_parameter('delete') \
            .add_query_string('id', file_id)
        return self.client.execute_request(self.request.build())
