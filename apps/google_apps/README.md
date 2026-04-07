# Google Apps Integration (`apps/google_apps`)

Google Workspace and Google Cloud API integrations for Calendar, Gmail, Keep, Sheets, Tasks, Drive, and Translation.

References:
- [Google API Console](https://console.cloud.google.com/apis/library)
- [Google Workspace APIs](https://developers.google.com/workspace)
- [OAuth 2.0 for Installed Apps](https://developers.google.com/identity/protocols/oauth2/native-app)

---

## Implemented APIs

| API | Service File | Scope | MCP Tools |
|-----|-------------|-------|-----------|
| Google Calendar | `calendar.py` | `calendar.readonly` | `get_google_calendar_events_today`, `get_google_calendar_holidays` |
| Gmail | `gmail.py` | `gmail.readonly` | `get_gmail_recent_emails`, `search_gmail` |
| Google Keep | `keep.py` | `keep` | `list_google_keep_notes`, `get_google_keep_note`, `create_google_keep_note` |
| Google Sheets | `sheets.py` | `spreadsheets` | None (code only) |
| **Google Tasks** | `tasks.py` | `tasks` | `list_google_task_lists`, `list_google_tasks`, `list_all_google_tasks`, `create_google_task`, `complete_google_task` |
| **Google Drive** | `drive.py` | `drive` | `list_google_drive_files`, `search_google_drive`, `get_google_drive_file`, `get_google_drive_storage`, `list_google_drive_folders` |
| **Translation** | `translation.py` | API key | `translate_text`, `detect_language`, `list_translation_languages` |

---

## Setup

### 1. Create a Google Cloud Project

1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the APIs you need — see per-service sections below
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Select **Desktop app**, download the JSON, save as `.env/credentials.json`

### 2. Authentication

**OAuth 2.0 (Calendar, Gmail, Keep, Tasks, Drive)**

Each service uses its own `storage-*.json` token file to avoid scope conflicts. On first run, a browser window opens for consent. Subsequent runs use the saved token (auto-refreshed).

| Config Key | Credentials | Storage | Scope |
|-----------|-------------|---------|-------|
| `GOOGLE_APPS` | `credentials.json` | `storage.json` | `calendar.readonly`, `spreadsheets` |
| `GOOGLE_GMAIL` | `credentials.json` | `storage-gmail.json` | `gmail.readonly` |
| `GOOGLE_KEEP` | `credentials-ha.json` | `storage-ha.json` | `keep` |
| `GOOGLE_TASKS` | `credentials.json` | `storage-tasks.json` | `tasks` |
| `GOOGLE_DRIVE` | `credentials.json` | `storage-drive.json` | `drive` |

**API Key (Translation)**

Translation uses a Google Cloud API key (`GOOGLE_APPS_API_KEY`). Enable the Cloud Translation API in the console and copy the key.

### 3. Environment Variables

Add to `.env/apps.env`:

```env
GOOGLE_APPS_API_KEY=your_api_key
```

All OAuth flows use `credentials.json` and `credentials-ha.json` placed in `.env/`.

### 4. Enable APIs in Google Cloud Console

| API | Console Link | Used By |
|-----|-------------|---------|
| Google Calendar API | [Enable](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com) | Calendar |
| Gmail API | [Enable](https://console.cloud.google.com/apis/library/gmail.googleapis.com) | Gmail |
| Google Keep API | [Enable](https://console.cloud.google.com/apis/library/keep.googleapis.com) | Keep |
| Tasks API | [Enable](https://console.cloud.google.com/apis/library/tasks.googleapis.com) | Tasks |
| Google Drive API | [Enable](https://console.cloud.google.com/apis/library/drive.googleapis.com) | Drive |
| Cloud Translation API | [Enable](https://console.cloud.google.com/apis/library/translate.googleapis.com) | Translation |

---

## Google Keep — Not Available for Third-Party Apps

The Google Keep API scope (`https://www.googleapis.com/auth/keep`) is **not publicly available** for third-party OAuth applications. It does not appear in the Google Cloud Console scope picker and cannot be added to an OAuth consent screen.

Google restricts this scope to:
- Google Workspace add-ons (requires a formal publishing process)
- Apps explicitly approved by Google (partner program)

This is a Google policy restriction — not a configuration issue. Keep tests are permanently skipped.

**Use Google Tasks instead** — it is fully implemented, works on all account types (personal and Workspace), and covers the same automation use cases:

| Keep | Tasks equivalent |
|------|-----------------|
| Notes | Tasks with notes field |
| Labels | Task lists |
| Reminders | Due dates |
| Archive | Complete task |
| Trash | Delete task |

The Keep service code (`keep.py`, MCP tools) remains in place in case Google opens access in the future.

---

## API Services

### `ApiServiceGoogleTasks`

Requires scope: `https://www.googleapis.com/auth/tasks`

| Method | Description |
|--------|-------------|
| `list_task_lists()` | List all task lists |
| `get_task_list(tasklist_id)` | Get a task list by ID |
| `create_task_list(title)` | Create a new task list |
| `delete_task_list(tasklist_id)` | Delete a task list |
| `list_tasks(tasklist_id, show_completed, ...)` | List tasks in a task list |
| `get_task(task_id, tasklist_id)` | Get a task by ID |
| `create_task(title, notes, due, tasklist_id)` | Create a new task |
| `update_task(task_id, updates, tasklist_id)` | Update task fields |
| `complete_task(task_id, tasklist_id)` | Mark task as completed |
| `delete_task(task_id, tasklist_id)` | Delete a task |
| `clear_completed_tasks(tasklist_id)` | Remove all completed tasks |
| `list_all_tasks(show_completed)` | All tasks across all task lists |

Use `'@default'` as `tasklist_id` to target the default task list.

---

### `ApiServiceGoogleDrive`

Requires scope: `https://www.googleapis.com/auth/drive`

| Method | Description |
|--------|-------------|
| `list_files(query, page_size, order_by)` | List files with optional Drive query |
| `search_files(name, mime_type, parent_id)` | Search files by name/type/location |
| `get_file(file_id)` | Get file metadata |
| `download_file(file_id)` | Download file content as bytes |
| `export_file(file_id, mime_type)` | Export Google Workspace files (Docs → PDF, Sheets → CSV, etc.) |
| `upload_file(name, content, mime_type, parent_id)` | Upload from bytes |
| `upload_file_from_path(file_path, name, ...)` | Upload from local file path |
| `create_folder(name, parent_id)` | Create a folder |
| `list_folders(parent_id)` | List folders in a directory |
| `delete_file(file_id)` | Permanently delete a file/folder |
| `copy_file(file_id, name, parent_id)` | Copy a file |
| `get_storage_quota()` | Get storage usage/limit (bytes) |

**Drive query syntax** (for `list_files`):
```python
# Files containing "report" in the name
"name contains 'report'"

# All PDFs
"mimeType = 'application/pdf'"

# Files in a specific folder
"'FOLDER_ID' in parents"

# Recently modified images
"mimeType contains 'image/' and modifiedTime > '2026-01-01T00:00:00'"
```

---

### `ApiServiceGoogleTranslation`

Auth: API key (`GOOGLE_APPS_API_KEY`). Free tier: 500,000 characters/month.

| Method | Description |
|--------|-------------|
| `translate(text, target, source, text_format)` | Translate text to a target language |
| `detect_language(text)` | Detect the language of a text |
| `list_languages(target)` | List all supported language codes and names |

**Common language codes:** `en` English, `es` Spanish, `fr` French, `de` German, `ja` Japanese, `zh` Chinese (Simplified), `tl` Filipino, `ko` Korean, `ar` Arabic

---

## Tests

```sh
# Run all Google Apps tests
pytest apps/google_apps/tests/ -v

# Specific services
pytest apps/google_apps/tests/test_tasks.py -v
pytest apps/google_apps/tests/test_drive.py -v
pytest apps/google_apps/tests/test_translation.py -v

# Smoke tests only
pytest apps/google_apps/tests/ -m smoke -v
```

Tests are live integration tests. OAuth tests open a browser on first run to complete the consent flow. Translation tests require `GOOGLE_APPS_API_KEY` to be set.

---

## MCP Tools Summary

| Tool | Service |
|------|---------|
| `get_google_calendar_events_today` | Calendar |
| `get_google_calendar_holidays` | Calendar |
| `list_google_keep_notes` | Keep |
| `get_google_keep_note` | Keep |
| `create_google_keep_note` | Keep |
| `get_gmail_recent_emails` | Gmail |
| `search_gmail` | Gmail |
| `list_google_task_lists` | Tasks |
| `list_google_tasks` | Tasks |
| `list_all_google_tasks` | Tasks |
| `create_google_task` | Tasks |
| `complete_google_task` | Tasks |
| `list_google_drive_files` | Drive |
| `search_google_drive` | Drive |
| `get_google_drive_file` | Drive |
| `get_google_drive_storage` | Drive |
| `list_google_drive_folders` | Drive |
| `translate_text` | Translation |
| `detect_language` | Translation |
| `list_translation_languages` | Translation |
