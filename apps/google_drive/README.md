# Google Drive Integration

Google Drive file operations exposed through the HARQIS MCP server.

## Setup

The `GOOGLE_DRIVE` block in `apps_config.yaml` uses Drive API v3 with the
`https://www.googleapis.com/auth/drive` scope. Configure the referenced Google
OAuth client file (`credentials.json`) and token storage (`storage-drive.json`)
for the host. Keep both credential artifacts out of Git.

## MCP tools

| Tool | Purpose |
|---|---|
| `google_drive_upload_text` | Create a text-backed Drive file. |
| `google_drive_upload_from_path` | Upload a local file. |
| `google_drive_download_text` | Download file content as text. |
| `google_drive_export_text` | Export a Google Workspace document. |
| `google_drive_create_folder` | Create a folder. |
| `google_drive_copy_file` | Copy and optionally rename a file. |
| `google_drive_delete_file` | Delete a Drive file. |

The tools are registered by `register_google_drive_tools()` in
`mcp/server.py`. Upload, copy, folder creation, and deletion mutate the connected
Drive and require explicit target confirmation.
