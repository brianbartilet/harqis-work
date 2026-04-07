import logging

from mcp.server.fastmcp import FastMCP
from apps.apps_config import CONFIG_MANAGER
from apps.google_apps.config import CONFIG
from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendar, ApiServiceGoogleCalendarEvents, EventType
from apps.google_apps.references.web.api.keep import ApiServiceGoogleKeepNotes
from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail
from apps.google_apps.references.web.api.tasks import ApiServiceGoogleTasks
from apps.google_apps.references.web.api.drive import ApiServiceGoogleDrive
from apps.google_apps.references.web.api.translation import ApiServiceGoogleTranslation

logger = logging.getLogger("harqis-mcp.google_apps")

_KEEP_CONFIG = CONFIG_MANAGER.get("GOOGLE_KEEP")
_GMAIL_CONFIG = CONFIG_MANAGER.get("GOOGLE_GMAIL")
_TASKS_CONFIG = CONFIG_MANAGER.get("GOOGLE_TASKS")
_DRIVE_CONFIG = CONFIG_MANAGER.get("GOOGLE_DRIVE")
_TRANSLATION_CONFIG = CONFIG_MANAGER.get("GOOGLE_TRANSLATION")


def register_google_apps_tools(mcp: FastMCP):

    @mcp.tool()
    def get_google_calendar_events_today(event_type: str = "ALL") -> list[dict]:
        """Get Google Calendar events for today across all calendars.

        Args:
            event_type: Filter type — one of ALL, ALL_DAY, NOW, SCHEDULED, UPCOMING_UNTIL_EOD.
                        ALL returns every event today (default).
                        ALL_DAY returns only full-day events.
                        NOW returns events currently in progress.
                        SCHEDULED returns upcoming timed events from now to midnight.
                        UPCOMING_UNTIL_EOD returns upcoming events that also end before midnight.
        """
        logger.info("Tool called: get_google_calendar_events_today event_type=%s", event_type)
        try:
            filter_enum = EventType[event_type.upper()]
        except KeyError:
            filter_enum = EventType.ALL

        service = ApiServiceGoogleCalendarEvents(CONFIG)
        events = service.get_all_events_today(event_type=filter_enum)
        result = [
            {
                "summary": e.get("summary", ""),
                "start": e.get("start", {}),
                "end": e.get("end", {}),
                "calendarSummary": e.get("calendarSummary", ""),
                "status": e.get("status", ""),
                "description": e.get("description", ""),
            }
            for e in events
        ]
        logger.info("get_google_calendar_events_today returned %d event(s)", len(result))
        return result

    @mcp.tool()
    def get_google_calendar_holidays(country_code: str = "en.philippines") -> list[dict]:
        """Get public holidays from Google Calendar for a given country.

        Args:
            country_code: Google Calendar holiday calendar code, e.g. 'en.philippines' (default)
        """
        logger.info("Tool called: get_google_calendar_holidays country_code=%s", country_code)
        service = ApiServiceGoogleCalendar(CONFIG)
        holidays = service.get_holidays(country_code=country_code)
        result = holidays if isinstance(holidays, list) else []
        logger.info("get_google_calendar_holidays returned %d holiday(s)", len(result))
        return result

    @mcp.tool()
    def list_google_keep_notes(filter: str = None) -> list[dict]:
        """List Google Keep notes, optionally filtered.

        Args:
            filter: AIP-160 filter string, e.g. 'trashed=false'. Omit for default (non-trashed).
        """
        logger.info("Tool called: list_google_keep_notes filter=%s", filter)
        service = ApiServiceGoogleKeepNotes(_KEEP_CONFIG)
        notes = service.list_non_trashed_notes() if filter is None else service.list_all_notes(filter=filter)
        result = [
            {
                "name": n.get("name", ""),
                "title": n.get("title", ""),
                "createTime": n.get("createTime", ""),
                "updateTime": n.get("updateTime", ""),
                "trashed": n.get("trashed", False),
            }
            for n in notes
        ]
        logger.info("list_google_keep_notes returned %d note(s)", len(result))
        return result

    @mcp.tool()
    def get_google_keep_note(name: str) -> dict:
        """Get a specific Google Keep note by resource name.

        Args:
            name: Resource name of the note, e.g. 'notes/NOTE_ID'
        """
        logger.info("Tool called: get_google_keep_note name=%s", name)
        service = ApiServiceGoogleKeepNotes(_KEEP_CONFIG)
        note = service.get_note(name)
        logger.info("get_google_keep_note title=%s", note.get("title", "") if isinstance(note, dict) else "?")
        return note

    @mcp.tool()
    def create_google_keep_note(title: str, text: str) -> dict:
        """Create a new Google Keep note.

        Args:
            title: Note title
            text: Note body text
        """
        logger.info("Tool called: create_google_keep_note title=%s", title)
        service = ApiServiceGoogleKeepNotes(_KEEP_CONFIG)
        body = {
            "title": title,
            "body": {
                "text": {
                    "text": text
                }
            }
        }
        note = service.create_note(body)
        logger.info("create_google_keep_note created name=%s", note.get("name", "") if isinstance(note, dict) else "?")
        return note

    @mcp.tool()
    def get_gmail_recent_emails(max_results: int = 10, query: str = None) -> list[dict]:
        """Get recent emails from Gmail with subject, sender, date, snippet, and body.

        Args:
            max_results: Number of emails to return (default 10, max 500).
            query: Optional Gmail search query, e.g. 'is:unread', 'from:boss@example.com',
                   'subject:invoice'. Omit to return the most recent emails regardless of state.
        """
        logger.info("Tool called: get_gmail_recent_emails max_results=%d query=%s", max_results, query)
        service = ApiServiceGoogleGmail(_GMAIL_CONFIG)
        emails = service.get_recent_emails(max_results=max_results, query=query)
        logger.info("get_gmail_recent_emails returned %d email(s)", len(emails))
        return emails

    @mcp.tool()
    def search_gmail(query: str, max_results: int = 20) -> list[dict]:
        """Search Gmail using a query string and return matching emails.

        Args:
            query: Gmail search string (same syntax as the Gmail search box),
                   e.g. 'is:unread label:inbox', 'from:noreply@github.com', 'has:attachment'.
            max_results: Maximum number of results to return (default 20).
        """
        logger.info("Tool called: search_gmail query=%s max_results=%d", query, max_results)
        service = ApiServiceGoogleGmail(_GMAIL_CONFIG)
        emails = service.get_recent_emails(max_results=max_results, query=query)
        logger.info("search_gmail returned %d email(s)", len(emails))
        return emails

    # ── Google Tasks ──────────────────────────────────────────────────────

    @mcp.tool()
    def list_google_task_lists() -> list[dict]:
        """List all Google Task lists for the authenticated user.

        Returns:
            List of task list dicts with id and title.
        """
        logger.info("Tool called: list_google_task_lists")
        service = ApiServiceGoogleTasks(_TASKS_CONFIG)
        result = service.list_task_lists()
        logger.info("list_google_task_lists returned %d list(s)", len(result))
        return result

    @mcp.tool()
    def list_google_tasks(tasklist_id: str = '@default',
                          show_completed: bool = False) -> list[dict]:
        """List tasks in a Google Task list.

        Args:
            tasklist_id:    Task list ID. '@default' uses the default list.
            show_completed: Include completed tasks. Default False.

        Returns:
            List of task dicts with id, title, status, due, notes.
        """
        logger.info("Tool called: list_google_tasks tasklist=%s", tasklist_id)
        service = ApiServiceGoogleTasks(_TASKS_CONFIG)
        result = service.list_tasks(tasklist_id=tasklist_id, show_completed=show_completed)
        logger.info("list_google_tasks returned %d task(s)", len(result))
        return result

    @mcp.tool()
    def list_all_google_tasks(show_completed: bool = False) -> list[dict]:
        """List all Google Tasks across all task lists.

        Args:
            show_completed: Include completed tasks. Default False.

        Returns:
            Flat list of task dicts, each with a taskListTitle field.
        """
        logger.info("Tool called: list_all_google_tasks")
        service = ApiServiceGoogleTasks(_TASKS_CONFIG)
        result = service.list_all_tasks(show_completed=show_completed)
        logger.info("list_all_google_tasks returned %d task(s)", len(result))
        return result

    @mcp.tool()
    def create_google_task(title: str, notes: str = None,
                           due: str = None,
                           tasklist_id: str = '@default') -> dict:
        """Create a new Google Task.

        Args:
            title:       Task title.
            notes:       Optional task notes/description.
            due:         Optional due date in RFC 3339 format (e.g. '2026-04-10T00:00:00.000Z').
            tasklist_id: Target task list ID. Default '@default'.

        Returns:
            Created task dict with id, title, status.
        """
        logger.info("Tool called: create_google_task title=%s", title)
        service = ApiServiceGoogleTasks(_TASKS_CONFIG)
        result = service.create_task(title=title, notes=notes, due=due, tasklist_id=tasklist_id)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def complete_google_task(task_id: str, tasklist_id: str = '@default') -> dict:
        """Mark a Google Task as completed.

        Args:
            task_id:     Task ID.
            tasklist_id: Task list ID. Default '@default'.

        Returns:
            Updated task dict with status='completed'.
        """
        logger.info("Tool called: complete_google_task task_id=%s", task_id)
        service = ApiServiceGoogleTasks(_TASKS_CONFIG)
        result = service.complete_task(task_id=task_id, tasklist_id=tasklist_id)
        return result if isinstance(result, dict) else {}

    # ── Google Drive ──────────────────────────────────────────────────────

    @mcp.tool()
    def list_google_drive_files(query: str = None, page_size: int = 50) -> list[dict]:
        """List files in Google Drive.

        Args:
            query:     Drive query string, e.g. "name contains 'report'",
                       "mimeType='application/pdf'", "'root' in parents".
                       Omit to list recent files.
            page_size: Max files to return (1–1000). Default 50.

        Returns:
            List of file metadata dicts with id, name, mimeType, size, modifiedTime.
        """
        logger.info("Tool called: list_google_drive_files query=%s", query)
        service = ApiServiceGoogleDrive(_DRIVE_CONFIG)
        result = service.list_files(query=query, page_size=page_size)
        logger.info("list_google_drive_files returned %d file(s)", len(result))
        return result

    @mcp.tool()
    def search_google_drive(name: str = None, mime_type: str = None,
                            parent_id: str = None) -> list[dict]:
        """Search Google Drive files by name, MIME type, or parent folder.

        Args:
            name:      Partial filename to search for.
            mime_type: MIME type filter, e.g. 'application/pdf', 'image/jpeg'.
            parent_id: Restrict to files inside this folder ID. 'root' for Drive root.

        Returns:
            List of matching file metadata dicts.
        """
        logger.info("Tool called: search_google_drive name=%s mime_type=%s", name, mime_type)
        service = ApiServiceGoogleDrive(_DRIVE_CONFIG)
        result = service.search_files(name=name, mime_type=mime_type, parent_id=parent_id)
        logger.info("search_google_drive returned %d result(s)", len(result))
        return result

    @mcp.tool()
    def get_google_drive_file(file_id: str) -> dict:
        """Get metadata for a Google Drive file or folder by ID.

        Args:
            file_id: Drive file ID.

        Returns:
            File metadata dict with id, name, mimeType, size, modifiedTime, webViewLink.
        """
        logger.info("Tool called: get_google_drive_file file_id=%s", file_id)
        service = ApiServiceGoogleDrive(_DRIVE_CONFIG)
        result = service.get_file(file_id)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_google_drive_storage() -> dict:
        """Get Google Drive storage quota for the authenticated user.

        Returns:
            Dict with limit, usage, usageInDrive, usageInDriveTrash (in bytes).
        """
        logger.info("Tool called: get_google_drive_storage")
        service = ApiServiceGoogleDrive(_DRIVE_CONFIG)
        result = service.get_storage_quota()
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def list_google_drive_folders(parent_id: str = None) -> list[dict]:
        """List folders in Google Drive.

        Args:
            parent_id: Parent folder ID to list inside. Omit for root-level folders.

        Returns:
            List of folder metadata dicts with id, name, mimeType.
        """
        logger.info("Tool called: list_google_drive_folders parent_id=%s", parent_id)
        service = ApiServiceGoogleDrive(_DRIVE_CONFIG)
        result = service.list_folders(parent_id=parent_id)
        logger.info("list_google_drive_folders returned %d folder(s)", len(result))
        return result

    # ── Google Translation ────────────────────────────────────────────────

    @mcp.tool()
    def translate_text(text: str, target: str, source: str = None) -> dict:
        """Translate text using Google Cloud Translation API.

        Args:
            text:   Text to translate.
            target: Target language code (BCP-47), e.g. 'es', 'fr', 'ja', 'tl', 'zh'.
            source: Source language code. Auto-detected if omitted.

        Returns:
            Dict with data.translations list. Each item has translatedText and
            optionally detectedSourceLanguage.
        """
        logger.info("Tool called: translate_text target=%s", target)
        service = ApiServiceGoogleTranslation(_TRANSLATION_CONFIG)
        result = service.translate(text=text, target=target, source=source)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def detect_language(text: str) -> dict:
        """Detect the language of a text string using Google Translation API.

        Args:
            text: Text whose language to detect.

        Returns:
            Dict with data.detections list. Each detection has language, confidence, isReliable.
        """
        logger.info("Tool called: detect_language")
        service = ApiServiceGoogleTranslation(_TRANSLATION_CONFIG)
        result = service.detect_language(text=text)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def list_translation_languages(target: str = 'en') -> dict:
        """List all languages supported by Google Translation API.

        Args:
            target: Language code for localizing language names. Default 'en'.

        Returns:
            Dict with data.languages list, each with language code and name.
        """
        logger.info("Tool called: list_translation_languages target=%s", target)
        service = ApiServiceGoogleTranslation(_TRANSLATION_CONFIG)
        result = service.list_languages(target=target)
        return result if isinstance(result, dict) else {}
