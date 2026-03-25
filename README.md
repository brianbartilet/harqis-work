# HARQIS Work

## Introduction

- Real-world implementation of [HARQIS-core](https://github.com/brianbartilet/harqis-core), integrating 16+ third-party applications and automation layers.
- Demonstrates **RPA-like capabilities** implemented entirely in Python with Celery, n8n, and AI-driven workflows.
- Provides an extensible portfolio of automated routines for business, productivity, and personal systems.
- Think of it as a code-first RPA platform — every integration is a Python module, every scheduled routine is a Celery task.

---

## Getting Started

### Requirements

- **Python 3.12+**
- **RabbitMQ** (Celery broker, default: `amqp://guest:guest@localhost:5672/`)
- **Elasticsearch** (optional, for log shipping via `ELASTIC_LOGGING`)
- **Rainmeter** (Windows only, for desktop HUD skinning)
- **n8n** (optional, for orchestration via Docker or local install)

### Installation

1. Clone the repository:

   ```sh
   git clone https://github.com/brianbartilet/harqis-work.git
   cd harqis-work
   ```

2. Create and activate a virtual environment:

   ```sh
   python -m venv venv
   source venv/bin/activate        # Linux/macOS
   venv\Scripts\activate           # Windows
   ```

3. Upgrade pip and install dependencies:

   ```sh
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

   > The sole dependency is `harqis-core` (installed from GitHub). It provides all base classes, Celery setup, REST client utilities, Selenium page object base, and configuration loaders.

4. To force-reinstall `harqis-core` from the latest commit:

   ```sh
   pip install --upgrade --force-reinstall --no-cache-dir git+https://github.com/brianbartilet/harqis-core.git#egg=harqis-core
   ```

---

## Configuration

### Environment Variables (`.env/apps.env`)

All sensitive credentials are injected via environment variables. Create `.env/apps.env` and populate the variables below:

```env
# ---------------------------------------------------------------------------
# Celery / RabbitMQ
# Default broker uses guest:guest@localhost:5672 — override in apps_config.yaml
# if your RabbitMQ instance uses different credentials or host.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# n8n  —  local workflow orchestrator (http://localhost:5678)
# Generate an API key from n8n Settings > API
# ---------------------------------------------------------------------------
N8N_API_KEY=

# ---------------------------------------------------------------------------
# OpenAI  —  GPT models and Assistants API
# OPENAI_API_KEY        : platform.openai.com → API Keys
# OPENAI_ASSISTANT_ID   : default assistant ID used by hud_gpt tasks
# OPENAI_ASSISTANT_DESKTOP : assistant ID for desktop log analysis
# OPENAI_ASSISTANT_REPORTER : assistant ID for report generation
# ---------------------------------------------------------------------------
OPENAI_API_KEY=
OPENAI_ASSISTANT_ID=
OPENAI_ASSISTANT_DESKTOP=
OPENAI_ASSISTANT_REPORTER=

# ---------------------------------------------------------------------------
# Anthropic  —  Claude API
# console.anthropic.com → API Keys
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY=

# ---------------------------------------------------------------------------
# OANDA  —  Forex trading (REST API v3)
# OANDA_BEARER_TOKEN   : personal access token from OANDA My Account
# OANDA_MT4_ACCOUNT_ID : numeric account ID (used in API calls)
# ---------------------------------------------------------------------------
OANDA_BEARER_TOKEN=
OANDA_MT4_ACCOUNT_ID=

# ---------------------------------------------------------------------------
# Echo MTG  —  MTG collection management (echomtg.com)
# Primary account: used for standard inventory queries
# Bulk account   : used for high-volume listing operations
# ---------------------------------------------------------------------------
ECHO_MTG_USER=
ECHO_MTG_PASSWORD=

ECHO_MTG_BULK_USER=
ECHO_MTG_BULK_PASSWORD=
ECHO_MTG_BULK_BEARER_TOKEN=

# ---------------------------------------------------------------------------
# Scryfall  —  MTG card database (no auth required, path only)
# SCRY_DOWNLOADS_PATH : local folder where bulk JSON files are saved
#                       e.g. C:\data\scryfall
# ---------------------------------------------------------------------------
SCRY_DOWNLOADS_PATH=

# ---------------------------------------------------------------------------
# TCG Marketplace  —  card resale platform (thetcgmarketplace.com)
# TCG_MP_USER_ID  : numeric user ID returned after login
# TCG_SAVE        : local folder for saving order/listing exports
#                   e.g. C:\data\tcg
# ---------------------------------------------------------------------------
TCG_MP_USER_ID=
TCG_MP_USERNAME=
TCG_MP_PASSWORD=
TCG_SAVE=

# ---------------------------------------------------------------------------
# Rainmeter  —  Windows desktop HUD skinning
# RAINMETER_BIN_PATH           : path to Rainmeter.exe
#                                e.g. C:\Program Files\Rainmeter\Rainmeter.exe
# RAINMETER_STATIC_PATH        : path to static skin assets folder
# RAINMETER_WRITE_SKINS_TO_PATH: path where generated skins are written
# RAINMETER_WRITE_FEED_TO_PATH : path where HUD feed data files are written
# ---------------------------------------------------------------------------
RAINMETER_BIN_PATH=
RAINMETER_STATIC_PATH=
RAINMETER_WRITE_SKINS_TO_PATH=
RAINMETER_WRITE_FEED_TO_PATH=

# ---------------------------------------------------------------------------
# Google Apps  —  Calendar, Sheets, Keep (OAuth 2.0)
# GOOGLE_APPS_API_KEY : API key for non-OAuth endpoints (e.g. public calendar)
# OAuth credentials are stored in credentials.json / storage.json at repo root.
# Delete storage.json to re-trigger the OAuth consent flow.
# ---------------------------------------------------------------------------
GOOGLE_APPS_API_KEY=

# ---------------------------------------------------------------------------
# Elasticsearch  —  local log shipping (http://localhost:9200)
# ELASTIC_API_KEY : preferred auth method (leave blank to use basic auth)
# ELASTIC_USER / ELASTIC_PASSWORD : used if use_basic_auth=True in config
# ---------------------------------------------------------------------------
ELASTIC_API_KEY=
ELASTIC_USER=
ELASTIC_PASSWORD=

# ---------------------------------------------------------------------------
# Desktop capture  —  activity logging and file sync paths
# ACTIONS_LOG_PATH        : folder where timestamped activity logs are written
# ACTIONS_ARCHIVE_PATH    : folder where logs are archived by month
# ACTIONS_SCREENSHOT_PATH : folder where screenshots are saved
# DESKTOP_PATH_DEV        : source folder for copy_files_targeted task
# DESKTOP_PATH_RUN        : destination folder for copy_files_targeted task
# DESKTOP_PATH_I_CUE_PROFILES : path to iCUE profile files (Corsair)
# DESKTOP_PATH_FEED       : folder read by Rainmeter for HUD feed data
# ---------------------------------------------------------------------------
ACTIONS_LOG_PATH=
ACTIONS_ARCHIVE_PATH=
ACTIONS_SCREENSHOT_PATH=
DESKTOP_PATH_DEV=
DESKTOP_PATH_RUN=
DESKTOP_PATH_I_CUE_PROFILES=
DESKTOP_PATH_FEED=

# ---------------------------------------------------------------------------
# ElevenLabs  —  voice AI agents (agent IDs from ElevenLabs dashboard)
# ELEVEN_AGENT_N8N            : agent ID for n8n automation voice interface
# ELEVEN_AGENT_N8N_CHAT       : agent ID for conversational n8n interface
# ELEVEN_AGENT_N8N_CHAT_TESTS : agent ID for test/sandbox environment
# ---------------------------------------------------------------------------
ELEVEN_AGENT_N8N=
ELEVEN_AGENT_N8N_CHAT=
ELEVEN_AGENT_N8N_CHAT_TESTS=

# ---------------------------------------------------------------------------
# Python runner  —  Windows-specific paths for spawning subprocesses
# PYTHON_EXE : absolute path to the venv Python executable
#              e.g. C:\path\to\harqis-work\venv\Scripts\python.exe
# ENV_ROOT   : root directory of the project
#              e.g. C:\path\to\harqis-work
# ---------------------------------------------------------------------------
PYTHON_EXE=
ENV_ROOT=

# ---------------------------------------------------------------------------
# YNAB  —  You Need A Budget (api.youneedabudget.com)
# YNAB_ACCESS_TOKEN : personal access token from YNAB Account Settings
# YNAB_BUDGET_PHP   : budget ID for PHP (Philippine Peso) budget
# YNAB_BUDGET_SGD   : budget ID for SGD (Singapore Dollar) budget
# ---------------------------------------------------------------------------
YNAB_ACCESS_TOKEN=
YNAB_BUDGET_PHP=
YNAB_BUDGET_SGD=

# ---------------------------------------------------------------------------
# Moo / Futu  —  stock trading stub (not yet implemented)
# MOO_PWD_MD5 : MD5 hash of the Futu trading password
#               Required by the Futu OpenD local gateway (port 11111)
# ---------------------------------------------------------------------------
MOO_PWD_MD5=
```

### `apps_config.yaml`

Central YAML file at the repo root. Each section corresponds to one app. Sensitive values use `${ENV_VAR}` interpolation. Config is loaded at import time via `ConfigLoaderService` from harqis-core.

Key sections: `CELERY_TASKS`, `N8N`, `HARQIS_GPT`, `OANDA`, `ECHO_MTG`, `SCRYFALL`, `TCG_MP`, `RAINMETER`, `GOOGLE_APPS`, `GOOGLE_KEEP`, `ELASTIC_LOGGING`, `DESKTOP`, `YNAB`, `ANTHROPIC`, `MOO`.

### Google Apps OAuth

Google API uses OAuth 2.0 via credential files:
- `credentials.json` — OAuth client credentials (download from Google Cloud Console)
- `storage.json` — Cached OAuth token (auto-generated on first run)
- Delete `storage.json` to re-trigger the OAuth consent flow.

---

## Running Tests

All tests are **live integration tests** — no mocking. Requires valid `.env/apps.env` and `apps_config.yaml`.

```sh
# Run all tests (excludes workflows/)
pytest

# Run tests for a specific app
pytest apps/echo_mtg/tests/

# Run a single test file
pytest apps/tcg_mp/tests/test_service.py

# Run only smoke tests
pytest -m smoke

# Run only sanity tests
pytest -m sanity
```

---

## Running Celery Workers

```sh
# Start a worker for all queues
celery -A workflows.config worker --loglevel=info

# Start the Celery Beat scheduler
celery -A workflows.config beat --loglevel=info

# Run both together (development only)
celery -A workflows.config worker --beat --loglevel=info -Q hud,default,tcg
```

---

## Architecture

### Directory Structure

```
harqis-work/
├── apps/                       # App integrations (one folder per service)
│   ├── .template/              # Template for new apps
│   ├── aaa/                    # Philippine stock exchange (Selenium)
│   ├── antropic/               # Anthropic Claude API
│   ├── desktop/                # Windows desktop automation
│   ├── echo_mtg/               # MTG collection management (REST)
│   ├── google_apps/            # Google Workspace (Calendar, Sheets, Keep)
│   ├── investagrams/           # Philippine stock analytics (scraping)
│   ├── moo/                    # Stub — work in progress
│   ├── oanda/                  # Forex trading (REST)
│   ├── open_ai/                # OpenAI GPT (REST)
│   ├── own_tracks/             # GPS tracking (Docker/MQTT only)
│   ├── rainmeter/              # Windows desktop HUD skinning
│   ├── scryfall/               # MTG card database (REST)
│   ├── tcg_mp/                 # TCG Marketplace (REST, most complex)
│   ├── trello/                 # Kanban (references only)
│   └── ynab/                   # Personal budgeting (REST)
│
├── workflows/                  # Celery task definitions
│   ├── .template/              # Template for new workflows
│   ├── config.py               # Master Celery Beat schedule
│   ├── desktop/                # Git pulls, window mgmt, file sync
│   ├── finance/                # Stub — no tasks yet
│   ├── hud/                    # Desktop HUD display tasks (12 tasks)
│   ├── mobile/                 # Android screen capture
│   ├── n8n/                    # n8n utility helpers
│   ├── prompts/                # AI prompt templates (markdown)
│   └── purchases/              # TCG card resale pipeline
│
├── apps_config.yaml            # Central app configuration
├── pytest.ini                  # Test configuration
├── requirements.txt            # Python dependencies
├── logging.yaml                # Logging configuration
├── workflows.mapping           # Auto-generated Celery task map (do not edit)
└── conftest.py                 # Pytest session fixtures
```

### App Structure (Template)

Each app follows this layout:

```
apps/<app_name>/
├── config.py                   # Loads app section from apps_config.yaml
├── references/
│   ├── base_api_service.py     # Extends harqis-core BaseFixtureServiceRest
│   ├── base_page.py            # Extends harqis-core BaseFixturePageObject (Selenium)
│   ├── dto/                    # Dataclass-based data transfer objects
│   ├── models/                 # Data models (often extend DTOs)
│   ├── constants/              # Enums and static values
│   └── web/api/                # Concrete API service implementations
└── tests/
```

`config.py` pattern (same in every app):

```python
APP_NAME = 'ECHO_MTG'
CONFIG = AppConfigWSClient(**load_config[APP_NAME])
```

### Workflow Structure (Template)

```
workflows/<workflow>/
├── tasks_config.py             # Celery Beat schedule dict
├── tasks/                      # @SPROUT.task decorated functions
├── dto/                        # Task parameter DTOs
└── tests/
```

Task decorator chain pattern:

```python
@SPROUT.task(queue='hud')
@log_result()           # Logs output to Elasticsearch
@init_meter(...)        # Initializes Rainmeter desktop widget
@feed()                 # Pushes data to desktop HUD feed
def show_calendar_information(**kwargs):
    ...
```

---

## App Inventory

| App | Integration | Type | Tests |
|-----|-------------|------|-------|
| `aaa` | Philippine stock exchange (PSEI) | Selenium | Yes |
| `antropic` | Anthropic Claude API | REST (native SDK) | Yes |
| `desktop` | Windows desktop automation | Local | No |
| `echo_mtg` | MTG collection management | REST API | Yes |
| `google_apps` | Calendar, Sheets, Keep | REST API (OAuth) | Yes |
| `investagrams` | Philippine stock analytics | Web scraping | No |
| `moo` | Futu/Moo trading stub | Stub | No |
| `oanda` | Forex trading | REST API | Yes |
| `open_ai` | OpenAI GPT | REST (native SDK) | No |
| `own_tracks` | GPS tracking | Docker/MQTT only | No |
| `rainmeter` | Windows desktop HUD skinning | Local | No |
| `scryfall` | MTG card database | REST API | Yes |
| `tcg_mp` | TCG Marketplace | REST API | Yes |
| `trello` | Kanban board | REST (refs only) | No |
| `ynab` | Personal budgeting | REST API | Yes |

---

## Workflow Inventory

Active Celery Beat schedules are merged in `workflows/config.py`:

```python
CONFIG_DICTIONARY = WORKFLOW_PURCHASES | WORKFLOWS_HUD | WORKFLOWS_DESKTOP
SPROUT.conf.beat_schedule = CONFIG_DICTIONARY
```

| Workflow | Status | Tasks | Description |
|----------|--------|-------|-------------|
| `hud` | Active | 12 | Calendar, forex, TCG orders, AI log analysis, YNAB budgets, Rainmeter skins |
| `purchases` | Active | 3 (+1 disabled) | MTG card resale pipeline: Scryfall bulk → card matching → listings → pricing → audit |
| `desktop` | Active | 7 | Git pulls, window management, file sync, activity capture, daily/weekly summaries |
| `mobile` | Active | 1 (unscheduled) | Android screen capture and OCR logging |
| `finance` | Stub | 0 | No tasks defined |
| `prompts` | Active | — | AI prompt templates used by hud/desktop workflows |
| `n8n` | Utilities | — | Shell utilities and ngrok helpers for n8n integration |

### Celery Task Queues

| Queue | Used By |
|-------|---------|
| `hud` | All `workflows.hud.tasks.*` |
| `tcg` | TCG card processing tasks |
| `default` | Desktop and general tasks |

---

## Mapping Files

HARQIS uses lightweight JSON-like mapping files to expose Celery tasks and shell commands to n8n and AI orchestrators.

### Purpose

- Provide mountable configuration for n8n Docker workflows.
- Allow AI assistants (OpenAI, Claude, etc.) to parse available actions deterministically.
- Expose task definitions, commands, schedules, and arguments in a machine-readable form.

### Format

```text
{
    'run-job--example_task': {
        'task': 'workflows.module.tasks.example_task',
        'schedule': <crontab: */10 * * * *>,
        'args': ['PARAM'],
        'kwargs': {}
    },
    'command-run--open_notepad': {
        'cmd': 'notepad'
    }
}
```

- Keys follow: `run-job--<name>` or `command-run--<name>`
- `workflows.mapping` is **auto-generated** by a Celery management job — do not edit directly.
- `scripts.mapping` may be manually maintained for shell command bindings.

---

## Known Issues

- `logger.warn()` (deprecated) used in `tcg_mp_selling.py` — should be `logger.warning()`
- `generate_tcg_mappings` task is commented out in `purchases/tasks_config.py` — must be triggered manually or via n8n
- Worker functions in `tcg_mp_selling.py` re-import all dependencies inside the function body — required for `multiprocessing` on Windows (no `fork`)
- `own_tracks` has no Python integration code — Docker Compose runtime dependency only
- `moo` app is a hollow stub with no services or tests
- `aaa` tests use `unittest.TestCase` (not pytest-style), placed in `unit_tests.py`

---

## Contact

For questions or feedback: **[REDACTED_EMAIL](mailto:REDACTED_EMAIL)**

## License

Distributed under the [MIT License](LICENSE).
