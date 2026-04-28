"""Google Drive MCP tools — upload, download, export, manage files and folders."""
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.google_drive.config import CONFIG
from apps.google_apps.references.web.api.drive import ApiServiceGoogleDrive

logger = logging.getLogger("harqis-mcp.google_drive")


def register_google_drive_tools(mcp: FastMCP):

    @mcp.tool()
    def google_drive_upload_text(
        name: str,
        content: str,
        mime_type: str = "text/plain",
        parent_id: Optional[str] = None,
    ) -> dict:
        """Upload text content as a file to Google Drive.

        Args:
            name:      Filename to use in Drive.
            content:   Text content to upload.
            mime_type: MIME type of the file (default: text/plain).
            parent_id: Parent folder ID to upload into (default: My Drive root).
        """
        logger.info("Tool called: google_drive_upload_text name=%s", name)
        svc = ApiServiceGoogleDrive(CONFIG)
        result = svc.upload_file(
            name=name,
            content=content.encode("utf-8"),
            mime_type=mime_type,
            parent_id=parent_id,
        )
        logger.info("google_drive_upload_text id=%s", result.get("id"))
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def google_drive_upload_from_path(
        file_path: str,
        name: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> dict:
        """Upload a local file to Google Drive.

        Args:
            file_path: Local path to the file to upload.
            name:      Filename in Drive (default: local filename).
            parent_id: Parent folder ID (default: My Drive root).
        """
        logger.info("Tool called: google_drive_upload_from_path path=%s", file_path)
        svc = ApiServiceGoogleDrive(CONFIG)
        result = svc.upload_file_from_path(file_path=file_path, name=name, parent_id=parent_id)
        logger.info("google_drive_upload_from_path id=%s", result.get("id"))
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def google_drive_download_text(file_id: str) -> dict:
        """Download a file from Google Drive and return its text content.

        Note: Use google_drive_export_text for Google Docs/Sheets/Slides.

        Args:
            file_id: Google Drive file ID.
        """
        logger.info("Tool called: google_drive_download_text file_id=%s", file_id)
        svc = ApiServiceGoogleDrive(CONFIG)
        content_bytes = svc.download_file(file_id=file_id)
        text = content_bytes.decode("utf-8", errors="replace")
        logger.info("google_drive_download_text bytes=%d", len(content_bytes))
        return {"success": True, "file_id": file_id, "content": text, "size": len(content_bytes)}

    @mcp.tool()
    def google_drive_export_text(file_id: str, mime_type: str = "text/plain") -> dict:
        """Export a Google Workspace file (Doc, Sheet, Slide) to text or another format.

        Args:
            file_id:   Google Drive file ID.
            mime_type: Export MIME type. Common values:
                       'text/plain' (Docs → plain text),
                       'text/csv' (Sheets → CSV),
                       'application/pdf' (any → PDF).
        """
        logger.info("Tool called: google_drive_export_text file_id=%s mime=%s", file_id, mime_type)
        svc = ApiServiceGoogleDrive(CONFIG)
        content_bytes = svc.export_file(file_id=file_id, mime_type=mime_type)
        text = content_bytes.decode("utf-8", errors="replace") if "text" in mime_type else ""
        logger.info("google_drive_export_text bytes=%d", len(content_bytes))
        return {
            "success": True, "file_id": file_id, "mime_type": mime_type,
            "content": text, "size": len(content_bytes),
        }

    @mcp.tool()
    def google_drive_create_folder(name: str, parent_id: Optional[str] = None) -> dict:
        """Create a folder in Google Drive.

        Args:
            name:      Folder name.
            parent_id: Parent folder ID (default: My Drive root).
        """
        logger.info("Tool called: google_drive_create_folder name=%s", name)
        svc = ApiServiceGoogleDrive(CONFIG)
        result = svc.create_folder(name=name, parent_id=parent_id)
        logger.info("google_drive_create_folder id=%s", result.get("id"))
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def google_drive_copy_file(file_id: str, name: str, parent_id: Optional[str] = None) -> dict:
        """Copy a file to the same or a different folder in Google Drive.

        Args:
            file_id:   Source file ID.
            name:      Name for the copy.
            parent_id: Destination folder ID (default: same folder as source).
        """
        logger.info("Tool called: google_drive_copy_file file_id=%s name=%s", file_id, name)
        svc = ApiServiceGoogleDrive(CONFIG)
        result = svc.copy_file(file_id=file_id, name=name, parent_id=parent_id)
        logger.info("google_drive_copy_file new_id=%s", result.get("id"))
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def google_drive_delete_file(file_id: str) -> dict:
        """Permanently delete a file or folder from Google Drive.

        Args:
            file_id: Google Drive file or folder ID.
        """
        logger.info("Tool called: google_drive_delete_file file_id=%s", file_id)
        svc = ApiServiceGoogleDrive(CONFIG)
        svc.delete_file(file_id=file_id)
        logger.info("google_drive_delete_file deleted %s", file_id)
        return {"success": True, "file_id": file_id}
