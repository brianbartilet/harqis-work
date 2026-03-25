# Google Suite

## Description

- Integrations with [Google Workspace](https://workspace.google.com/) applications: Calendar, Sheets, and Keep.
- Uses the [Google Discovery API](https://developers.google.com/discovery) and OAuth 2.0 for authentication.
- Calendar is used by the `hud` workflow to display today's events and upcoming schedules.
- Sheets is used to read/write spreadsheet data for budgeting and tracking workflows.
- Keep is used for note management and lightweight task tracking.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## API Services

| Class | File | Methods |
|-------|------|---------|
| `ApiServiceGoogleCalendar` | `web/api/calendar.py` | `get_holidays()` |
| `ApiServiceGoogleCalendarEvents` | `web/api/calendar.py` | `list_events(calendar_id, start, end)`, `get_all_events_today(calendar_id, event_type)` |
| `ApiServiceGoogleSheets` | `web/api/sheets.py` | `get_values(range)`, `clear_values(range)`, `update_values(range, data)`, `reset_buffer()`, `set_headers(headers)`, `add_row(row)`, `set_rows(rows)`, `flush_buffer()` |
| `ApiServiceGoogleKeepNotes` | `web/api/keep.py` | `list_notes()`, `get_note(id)`, `create_note(title, text)`, `delete_note(id)`, `list_all_notes()`, `list_non_trashed_notes()` |

### Calendar Event Types (`get_all_events_today`)

| Type | Description |
|------|-------------|
| `ALL` | All events for today |
| `ALL_DAY` | Full-day events only |
| `NOW` | Currently active events |
| `SCHEDULED` | Future events scheduled today |
| `UPCOMING_UNTIL_EOD` | Events from now until end of day |

The `@holidays_aware()` decorator skips task execution if a holiday is detected on the calendar.

### Sheets Buffer API

`ApiServiceGoogleSheets` supports a buffered write pattern:

```python
sheets.set_headers(['Date', 'Amount', 'Category'])
sheets.add_row(['2026-03-25', '100', 'Food'])
sheets.add_row(['2026-03-25', '50', 'Transport'])
sheets.flush_buffer()   # Writes all buffered rows in one API call
```

## Configuration (`apps_config.yaml`)

```yaml
GOOGLE_APPS:
  app_id: 'google_apps'
  app_data:
    api_key: ${GOOGLE_APPS_API_KEY}
    credentials_file: 'credentials.json'
    storage_file: 'storage.json'
    scopes:
      - 'https://www.googleapis.com/auth/calendar.readonly'
      - 'https://www.googleapis.com/auth/spreadsheets'
      - 'https://www.googleapis.com/auth/keep'

GOOGLE_KEEP:
  app_id: 'google_keep'
  app_data:
    credentials_file: 'credentials.json'
    storage_file: 'storage.json'
```

`.env/apps.env`:

```env
GOOGLE_APPS_API_KEY=    # For non-OAuth public endpoints (e.g. public holiday calendar)
```

## OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable: **Google Calendar API**, **Google Sheets API**, **Google Keep API**.
3. Create OAuth 2.0 credentials (Desktop app type) and download as `credentials.json` to the repo root.
4. On first run, a browser window will open for the OAuth consent flow. After authorization, `storage.json` is created automatically.
5. To re-authorize, delete `storage.json` and re-run.

## How to Use

```python
from apps.google_apps.references.web.api.calendar import ApiServiceGoogleCalendarEvents
from apps.google_apps.config import CONFIG

cal = ApiServiceGoogleCalendarEvents(CONFIG)
events = cal.get_all_events_today('primary', event_type='UPCOMING_UNTIL_EOD')
```

```python
from apps.google_apps.references.web.api.sheets import ApiServiceGoogleSheets
from apps.google_apps.config import CONFIG

sheets = ApiServiceGoogleSheets(CONFIG, scopes_list=['https://www.googleapis.com/auth/spreadsheets'])
values = sheets.get_values('Sheet1!A1:D10')
sheets.add_row(['2026-03-25', 'value'])
sheets.flush_buffer()
```

## Notes

- Delete `storage.json` to re-trigger the OAuth consent flow.
- The `GOOGLE_APPS_API_KEY` is only needed for public endpoints (e.g. holiday calendars). Most services use OAuth.
- `sheets_utils.py` in `web/api/` contains additional helper functions for Sheets operations (untracked).
