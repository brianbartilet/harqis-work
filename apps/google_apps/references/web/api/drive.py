from __future__ import annotations

import io
from typing import Optional, Dict, Any, List

from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload, MediaInMemoryUpload

from apps.google_apps.references.web.discovery import BaseGoogleDiscoveryService


class ApiServiceGoogleDrive(BaseGoogleDiscoveryService):
    """
    Google Drive service using the discovery API (Drive v3).

    Wraps drive.googleapis.com v3:
      - files().list / get / create / update / delete / copy
      - files().get_media (download)

    Docs:
      https://developers.google.com/drive/api/reference/rest/v3

    Requires scope: https://www.googleapis.com/auth/drive
    """

    SERVICE_NAME = "drive"
    SERVICE_VERSION = "v3"

    def __init__(self, config, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self._files = self.service.files()

    # ── List / Search ─────────────────────────────────────────────────────

    def list_files(self, query: str = None, page_size: int = 50,
                   order_by: str = 'modifiedTime desc',
                   fields: str = 'files(id,name,mimeType,size,modifiedTime,parents)') -> List[Dict[str, Any]]:
        """
        List files in Google Drive.

        Args:
            query:     Drive query string (q parameter). E.g. "name contains 'report'",
                       "mimeType='application/pdf'", "'root' in parents".
            page_size: Max files to return (1–1000). Default 50.
            order_by:  Sort order. Default 'modifiedTime desc'.
            fields:    Comma-separated list of fields to return.

        Returns:
            List of file metadata dicts.
        """
        params: Dict[str, Any] = {
            'pageSize': page_size,
            'orderBy': order_by,
            'fields': f'nextPageToken,{fields}',
        }
        if query:
            params['q'] = query
        result = self._files.list(**params).execute()
        return result.get('files', [])

    def search_files(self, name: str = None, mime_type: str = None,
                     parent_id: str = None, page_size: int = 50) -> List[Dict[str, Any]]:
        """
        Search files by name, MIME type, and/or parent folder.

        Args:
            name:      Partial file name to search for (case-insensitive contains).
            mime_type: MIME type filter (e.g. 'application/pdf', 'image/jpeg',
                       'application/vnd.google-apps.folder').
            parent_id: Folder ID to restrict search to. Use 'root' for My Drive root.
            page_size: Max results. Default 50.

        Returns:
            List of matching file metadata dicts.
        """
        parts = ["trashed = false"]
        if name:
            parts.append(f"name contains '{name}'")
        if mime_type:
            parts.append(f"mimeType = '{mime_type}'")
        if parent_id:
            parts.append(f"'{parent_id}' in parents")
        query = ' and '.join(parts)
        return self.list_files(query=query, page_size=page_size)

    def get_file(self, file_id: str,
                 fields: str = 'id,name,mimeType,size,modifiedTime,parents,webViewLink') -> Dict[str, Any]:
        """
        Get metadata for a file or folder by ID.

        Args:
            file_id: Drive file ID.
            fields:  Fields to include in the response.

        Returns:
            File metadata dict.
        """
        return self._files.get(fileId=file_id, fields=fields).execute()

    # ── Download ──────────────────────────────────────────────────────────

    def download_file(self, file_id: str) -> bytes:
        """
        Download a file's binary content.

        Note: Google Workspace files (Docs, Sheets, Slides) cannot be downloaded
        directly — use export_file() instead.

        Args:
            file_id: Drive file ID.

        Returns:
            Raw file bytes.
        """
        request = self._files.get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def export_file(self, file_id: str, mime_type: str = 'text/plain') -> bytes:
        """
        Export a Google Workspace file (Docs, Sheets, Slides) to a specific format.

        Args:
            file_id:   Drive file ID.
            mime_type: Export format. E.g.:
                       'text/plain' (Docs → txt),
                       'application/pdf' (any → PDF),
                       'text/csv' (Sheets → CSV),
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' (Sheets → xlsx)

        Returns:
            Exported file bytes.
        """
        request = self._files.export_media(fileId=file_id, mimeType=mime_type)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    # ── Upload ────────────────────────────────────────────────────────────

    def upload_file(self, name: str, content: bytes, mime_type: str = 'application/octet-stream',
                    parent_id: str = None) -> Dict[str, Any]:
        """
        Upload a file to Google Drive from bytes.

        Args:
            name:      Filename to use in Drive.
            content:   File content as bytes.
            mime_type: MIME type of the file. Default 'application/octet-stream'.
            parent_id: Parent folder ID. None uploads to My Drive root.

        Returns:
            Created file metadata dict with id, name.
        """
        metadata: Dict[str, Any] = {'name': name}
        if parent_id:
            metadata['parents'] = [parent_id]
        media = MediaInMemoryUpload(content, mimetype=mime_type, resumable=False)
        return self._files.create(
            body=metadata,
            media_body=media,
            fields='id,name,mimeType,size,webViewLink',
        ).execute()

    def upload_file_from_path(self, file_path: str, name: str = None,
                               mime_type: str = None,
                               parent_id: str = None) -> Dict[str, Any]:
        """
        Upload a local file to Google Drive by file path.

        Args:
            file_path: Local path to the file.
            name:      Filename in Drive. Defaults to the local filename.
            mime_type: MIME type. Auto-detected if None.
            parent_id: Parent folder ID. None uploads to root.

        Returns:
            Created file metadata dict with id, name.
        """
        import os
        import mimetypes
        if not name:
            name = os.path.basename(file_path)
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or 'application/octet-stream'
        metadata: Dict[str, Any] = {'name': name}
        if parent_id:
            metadata['parents'] = [parent_id]
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        return self._files.create(
            body=metadata,
            media_body=media,
            fields='id,name,mimeType,size,webViewLink',
        ).execute()

    # ── Folders ───────────────────────────────────────────────────────────

    def create_folder(self, name: str, parent_id: str = None) -> Dict[str, Any]:
        """
        Create a folder in Google Drive.

        Args:
            name:      Folder name.
            parent_id: Parent folder ID. None creates in root.

        Returns:
            Created folder metadata dict with id, name.
        """
        metadata: Dict[str, Any] = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
        }
        if parent_id:
            metadata['parents'] = [parent_id]
        return self._files.create(
            body=metadata,
            fields='id,name,mimeType,webViewLink',
        ).execute()

    def list_folders(self, parent_id: str = None) -> List[Dict[str, Any]]:
        """
        List folders in a parent directory (or root if not specified).

        Args:
            parent_id: Parent folder ID. None lists root-level folders.

        Returns:
            List of folder metadata dicts.
        """
        parent = parent_id or 'root'
        return self.list_files(
            query=f"mimeType = 'application/vnd.google-apps.folder' and '{parent}' in parents and trashed = false"
        )

    # ── Manage ────────────────────────────────────────────────────────────

    def delete_file(self, file_id: str) -> None:
        """
        Permanently delete a file or folder.

        Args:
            file_id: Drive file or folder ID.
        """
        self._files.delete(fileId=file_id).execute()

    def copy_file(self, file_id: str, name: str,
                  parent_id: str = None) -> Dict[str, Any]:
        """
        Copy a file to the same or different folder.

        Args:
            file_id:   Source file ID.
            name:      Name for the copy.
            parent_id: Destination folder ID. None copies to root.

        Returns:
            Copied file metadata dict.
        """
        body: Dict[str, Any] = {'name': name}
        if parent_id:
            body['parents'] = [parent_id]
        return self._files.copy(
            fileId=file_id,
            body=body,
            fields='id,name,mimeType,webViewLink',
        ).execute()

    def get_storage_quota(self) -> Dict[str, Any]:
        """
        Get Drive storage quota information for the authenticated user.

        Returns:
            Dict with storageQuota containing limit, usage, usageInDrive, usageInDriveTrash (bytes).
        """
        result = self.service.about().get(fields='storageQuota').execute()
        return result.get('storageQuota', {})
