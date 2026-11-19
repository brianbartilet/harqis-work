# Installation and configuration

[Overview](../../README.md) · [Documentation index](README.md)

## Getting Started

### Requirements

- **Python 3.12+**
- **RabbitMQ** (Celery broker, default: `amqp://guest:guest@localhost:5672/`)
- **Elasticsearch** (optional, for log shipping via `ELASTIC_LOGGING`)
- **Rainmeter** (optional Windows-only legacy HUD; the Second Brain web HUD is portable)
- **n8n** (optional, for orchestration)

Read the [security and network migration guide](SECURITY.md) before starting services.
Docker ports now default to loopback; remote workers and devices need explicit private-interface bindings.

### Installation

```sh
git clone https://github.com/brianbartilet/harqis-work.git
cd harqis-work
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
.venv\Scripts\activate          # Windows
python -m pip install -r requirements.txt
pip check
```

To replace an existing environment cleanly while preserving the prior copy and
restoring locally running services:

```sh
python scripts/deploy.py --machine NAME --rebuild-venv
```

The rebuild re-executes under the base interpreter, installs the commit-pinned
`harqis-core` and all Work dependencies in one resolver pass, runs `pip check`
and import smoke tests, then rolls back automatically if verification fails.

---

## Configuration

### Environment Variables (`.env/apps.env`)

Keep credentials in this ignored local file and machine overrides in `machines.local.toml`.
Use the per-service `*_BIND_ADDRESS` settings in [Security](SECURITY.md#network-access)
only when a worker or device needs private-network access. Container-to-container
connections keep using service names. Never commit populated environment files.

These are common configuration variables, not an exhaustive list of every
runtime option. Consult each app/workflow's documentation and configuration for
additional settings. Keep this reference current when adding an app via
`/create-new-service-app`; never copy secret values from `.env/apps.env` into docs.

```env
# ── Core / harness ────────────────────────────────────────────────────────────
APP_CONFIG_FILE=                  # default: apps_config.yaml
WORKFLOW_CONFIG=                  # default: workflows.config

# ── Frontend dashboard ────────────────────────────────────────────────────────
APP_USERNAME=
APP_PASSWORD=
APP_SECRET_KEY=
HFL_CORPUS_API_URL=             # empty on canonical Mac; Mac frontend URL on remote readers
HFL_CORPUS_API_TOKEN=           # shared secret; keep in gitignored apps.env
HFL_API_HOST=                   # standalone HFL API bind address; default 0.0.0.0
HFL_API_PORT=                   # standalone HFL API port; default 8082
HFL_CORPUS_PATH=                # canonical host corpus root; /Volumes/harqis-data/hfl in production
HFL_OUTBOX_PATH=                # optional durable envelope directory; default logs/hfl-outbox
HFL_SESSION_AUDIT_PATH=         # optional sanitized prompt/outcome artifacts; default logs/hfl-session-audit
HFL_REFERENCE_ALLOWED_ROOTS=    # optional OS-pathsep list of trusted reference-download roots
HFL_SHARE_PUBLIC_URL=           # public HTTPS tunnel origin for generated share links
HFL_SHARE_SECRET_KEY=           # dedicated guest capability/session signing secret
HFL_SHARE_STORE_PATH=           # optional SQLite path; default .harqis-data/hfl-shares.sqlite3
HFL_SHARE_TRUST_PROXY_IDENTITY= # true only when Cloudflare Access is the exclusive origin path

# ── RabbitMQ / Celery broker ──────────────────────────────────────────────────
DOCKER_HOST_PORT_RABBIT_MQ=       # default: 15672
CELERY_BROKER=                    # default: amqp://guest:guest@localhost:5672/

# ── Elasticsearch + Kibana ────────────────────────────────────────────────────
ELASTIC_HOST=                     # default: http://localhost:9200
ELASTIC_USER=
ELASTIC_PASSWORD=
ELASTICSEARCH_PASSWORD=
KIBANA_HOST=                      # default: http://localhost:5601
KIBANA_SYSTEM_USER=               # default: kibana_system
KIBANA_SYSTEM_PASSWORD=
KIBANA_ANON_PASSWORD=
ELASTIC_API_KEY=

# ── n8n ───────────────────────────────────────────────────────────────────────
N8N_BASIC_AUTH_ACTIVE=            # true | false
N8N_BASIC_AUTH_USER=              # default: admin
N8N_API_KEY=

# ── Flower (Celery monitor) ───────────────────────────────────────────────────
FLOWER_USER=
FLOWER_PASSWORD=

# ── ngrok ─────────────────────────────────────────────────────────────────────
NGROK_AUTHTOKEN=

# ── Python runner ─────────────────────────────────────────────────────────────
PYTHON_EXE=                       # absolute path to your venv python
ENV_ROOT=                         # absolute path to repo root on this host

# ── AI / LLM ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=
ANTHROPIC_ADMIN_KEY=
TYPESAFE_API_KEY=                 # Jev decisions (execution host)
OPENAI_API_KEY=
OPENAI_ASSISTANT_ID=
OPENAI_ASSISTANT_DESKTOP=
OPENAI_ASSISTANT_REPORTER=
GEMINI_API_KEY=
GROK_API_KEY=
PERPLEXITY_API_KEY=

# ── ElevenLabs ────────────────────────────────────────────────────────────────
ELEVEN_LABS_API_KEY=
ELEVEN_AGENT_N8N=
ELEVEN_AGENT_N8N_CHAT=
ELEVEN_AGENT_N8N_CHAT_TESTS=

# ── Productivity / project management ─────────────────────────────────────────
TRELLO_API_KEY=
TRELLO_API_TOKEN=
JIRA_DOMAIN=                      # e.g. yourcompany.atlassian.net
JIRA_EMAIL=
JIRA_USER=
JIRA_API_TOKEN=
CONFLUENCE_DOMAIN=
CONFLUENCE_EMAIL=
CONFLUENCE_API_TOKEN=
NOTION_API_TOKEN=
AIRTABLE_API_TOKEN=               # personal access token (pat...)
APPSHEET_APPLICATION_ACCESS_KEY=  # per-app key — Manage → Integrations in your AppSheet app
APPSHEET_DEFAULT_APP_ID=          # default AppSheet app id (overridable per call)
APPSHEET_DEFAULT_TABLE=           # default table (overridable per call)

# Kanban orchestrator
KANBAN_BOARD_ID=                  # Trello board id or Jira project key

# Kanban agent personas (Mode A — per-agent Trello accounts).
# One pair per profile; leave blank to use Mode B (shared bot account
# + signed comments). Add new ones via `/create-new-kanban-profile <name>`.
TRELLO_AGENT_API_KEY__CODE=
TRELLO_AGENT_API_TOKEN__CODE=
TRELLO_AGENT_API_KEY__WRITE=
TRELLO_AGENT_API_TOKEN__WRITE=
TRELLO_AGENT_API_KEY__FULL=
TRELLO_AGENT_API_TOKEN__FULL=

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_API_TOKEN=                 # fine-grained PAT (ghp_...)

# ── Communication ─────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN=
DISCORD_DEFAULT_GUILD_ID=
DISCORD_DEFAULT_CHANNEL_ID=
TELEGRAM_BOT_TOKEN=
TELEGRAM_DEFAULT_CHAT_ID=
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_REDIRECT_URI=            # e.g. http://localhost:8099
LINKEDIN_PERSON_ID=
LINKEDIN_DEFAULT_POST_URN=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=
REDDIT_USER_AGENT=                # e.g. harqis-work:v1.0 (by /u/<you>)
REDDIT_DEFAULT_SUBREDDIT=

# ── Finance ───────────────────────────────────────────────────────────────────
ALPHA_VANTAGE_API_KEY=
OANDA_BEARER_TOKEN=
OANDA_MT4_ACCOUNT_ID=
STRIPE_API_KEY=                    # secret key — sk_live_... or sk_test_...
MOO_PWD_MD5=                      # configured Moo stub credential
YNAB_ACCESS_TOKEN=
YNAB_BUDGET_PHP=
YNAB_BUDGET_SGD=

# ── Magic: The Gathering ──────────────────────────────────────────────────────
ECHO_MTG_BEARER_TOKEN=
ECHO_MTG_USER=
ECHO_MTG_PASSWORD=
ECHO_MTG_BULK_BEARER_TOKEN=
ECHO_MTG_BULK_USER=
ECHO_MTG_BULK_PASSWORD=
SCRY_DOWNLOADS_PATH=              # local download dir for Scryfall bulk files
TCG_MP_USERNAME=
TCG_MP_PASSWORD=
TCG_MP_USER_ID=
TCG_SAVE=                         # local save dir for TCG marketplace exports
JUSTTCG_API_KEY=                  # JustTCG pricing API key (tcg_...)
POKEMON_TCG_API_KEY=              # Pokemon TCG API key (optional — keyless works at lower limits)
POKEMON_TCG_DATA_DUMP_PATH=       # local clone of PokemonTCG/pokemon-tcg-data (offline fallback)
MPC_EMAIL=                        # makeplayingcards.com account (proxy printing)
MPC_PASSWORD=
MPC_BROWSER_PROFILE_DIR=          # optional persistent Chromium profile (keeps MPC session)

# ── Web scraping / market research ────────────────────────────────────────────
APIFY_API_KEY=

# ── Music / media ─────────────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID=               # Spotify app client id (developer dashboard)
SPOTIFY_CLIENT_SECRET=           # Spotify app client secret
SPOTIFY_REFRESH_TOKEN=           # OAuth2 refresh token (minted once — see apps/spotify/README.md)

# ── Cloud / infrastructure ────────────────────────────────────────────────────
ORGO_API_KEY=
GOOGLE_APPS_API_KEY=              # shared Google/YouTube readiness signal
GOOGLE_SHEET_HARQIS_ID=            # HARQIS Google Sheet id
FILES_ENABLED=                    # opt-in Files scheduling; see docs/info/FILES-DEPLOYMENT.md
FILES_STORE_PATH=                 # absolute persistent catalog path on the server
FILES_HOST_ID=                    # stable catalog-host identity
FILES_ALLOWED_ROOTS=              # JSON array of approved local source roots
FILES_QUEUE=                      # files by default; only the catalog server consumes it
FILES_PUBLIC_URL=                 # public HTTPS frontend origin
FILES_GOOGLE_CONFIG_ID=           # GOOGLE_DRIVE by default
FILES_SFTP_PROFILES_PATH=          # private SSH connection profile JSON
FILES_MAX_BYTES=                  # per-file retrieval bound, default 2 GiB
FILES_SCAN_LIMIT=                 # discovered files per scan, default 100000
OWN_TRACKS_HOST=                  # default: localhost
OWN_TRACKS_PORT=                  # default: 8083
OWN_TRACKS_USERNAME=
OWN_TRACKS_PASSWORD=
OWN_TRACKS_DEFAULT_USER=
OWN_TRACKS_DEFAULT_DEVICE=

# ── Voice capture (Plaud) ─────────────────────────────────────────────────────
PLAUD_TOKEN=                      # cloud API bearer token (preferred)
PLAUD_EMAIL=                      # optional cloud login
PLAUD_PASSWORD=
PLAUD_EXPORT_DIR=                 # local export folder (fallback)
PLAUD_ARCHIVE_HOST=               # archive host (default: harqis-ones-mac-mini)
PLAUD_ARCHIVE_PATH=               # remote archive dir (unset → archive skipped)

# ── Android SDK ──────────────────────────────────────────────────────────────
ANDROID_SDK_ROOT=                 # Android SDK root for emulator/device tools

# ── Desktop capture / Rainmeter (Windows) ─────────────────────────────────────
ACTIONS_LOG_PATH=                 # absolute path
ACTIONS_ARCHIVE_PATH=             # absolute path
ACTIONS_SCREENSHOT_PATH=          # absolute path
DESKTOP_PATH_DEV=                 # repo path on this host
DESKTOP_PATH_RUN=                 # runtime path on this host
DESKTOP_PATH_FEED=                # feed output path
DESKTOP_PATH_I_CUE_PROFILES=      # Corsair iCUE profiles dir
RAINMETER_BIN_PATH=               # path to Rainmeter.exe
RAINMETER_STATIC_PATH=
RAINMETER_WRITE_SKINS_TO_PATH=
RAINMETER_WRITE_FEED_TO_PATH=
```

> The actual `.env/apps.env` file is **gitignored** — values shown here are
> placeholders. Variables are consumed by `apps_config.yaml` interpolation or
> directly by runtime code. MCP registration is filtered by `MCP_ENABLED_APPS`;
> registrar import/configuration failures are logged as warnings and skipped.
> Missing credentials do not universally prevent registration: some tools fail
> only when called.

### `apps_config.yaml`

Central YAML at the repo root. Each section maps to one app. Sensitive values use `${ENV_VAR}` interpolation, loaded at import time via `ConfigLoaderService`.

### Google Apps OAuth

- `credentials.json` — OAuth client credentials (from Google Cloud Console)
- `storage.json` — Cached OAuth token (auto-generated on first run; delete to re-auth)

---
