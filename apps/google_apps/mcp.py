import logging

from mcp.server.fastmcp import FastMCP
from apps.apps_config import CONFIG_MANAGER
from apps.google_apps.config import CONFIG
from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendar, ApiServiceGoogleCalendarEvents, EventType
from apps.google_apps.references.web.api.keep import ApiServiceGoogleKeepNotes
from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail

logger = logging.getLogger("harqis-mcp.google_apps")

_KEEP_CONFIG = CONFIG_MANAGER.get("GOOGLE_KEEP")
_GMAIL_CONFIG = CONFIG_MANAGER.get("GOOGLE_GMAIL")


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
