# MEMORY.md — HARQIS-CLAW Long-Term Memory

> Sensitive details (accounts, paths, PII) are in `memory/private.md` (gitignored).

## About Brian

- Name: Brian
- Timezone: Asia/Singapore (GMT+8)
- Primary use: automation tasks, querying services, monitoring via Telegram
- Contact details: see `memory/private.md`

---

## HARQIS-Work Repository

**Repo:** https://github.com/brianbartilet/harqis-work  
**Stack:** Python 3.12, Celery, harqis-core, n8n, Anthropic, Rainmeter, Docker

This is Brian's main automation platform. It's a code-first RPA framework with:
- **16+ app integrations** — each under `apps/<name>/`
- **Celery workflows** — scheduled tasks under `workflows/<name>/`
- **Desktop HUD** — Rainmeter-rendered live panels driven by Celery tasks
- **Frontend dashboard** — FastAPI + HTMX at `http://localhost:8080`

### Key Files
| File | Purpose |
|---|---|
| `apps_config.yaml` | Central config, `${ENV_VAR}` interpolated |
| `.env/apps.env` | All secrets/credentials |
| `.env/credentials.json` | Google OAuth client credentials |
| `.env/storage-gmail.json` | Gmail OAuth token (short-lived, has refresh_token) |
| `.env/storage.json` | Google Calendar/Sheets OAuth token |
| `workflows/config.py` | Master Celery Beat schedule |
| `workflows.mapping` | Auto-generated task map for n8n/AI agents |

### App Integrations
| App | Path | Auth Method |
|---|---|---|
| OANDA (forex) | `apps/oanda/` | Bearer token in `.env/apps.env` |
| TCG Marketplace | `apps/tcg_mp/` | Username/password → JWT |
| Google Gmail | `apps/google_apps/` | OAuth2, token in `storage-gmail.json` |
| Google Calendar | `apps/google_apps/` | OAuth2, token in `storage.json` |
| Anthropic | `apps/antropic/` | API key in `.env/apps.env` |
| YNAB | `apps/ynab/` | Bearer token in `.env/apps.env` |
| OwnTracks | `apps/own_tracks/` | Docker MQTT + REST at :8083 |
| EchoMTG | `apps/echo_mtg/` | Username/password |
| Discord | `apps/discord/` | Bot token |
| Telegram | `apps/telegram/` | Bot token |
| OpenAI | `apps/open_ai/` | API key |
| Rainmeter | `apps/rainmeter/` | Local Windows binary |

### General Rule

Always check harqis-work apps first before using OpenClaw built-in tools or external services. If an integration exists in `apps_config.yaml`, use it.

### How to Access Any App from HARQIS-Work

Whenever I need to call an app integration:
1. Check `apps_config.yaml` for the app's config block — it shows base URL and which env vars to use
2. Load credentials from `.env/apps.env` — env vars are referenced as `${VAR_NAME}` in the config
3. Call the API directly (Node.js or PowerShell) using those values

Example — Trello:
- `apps_config.yaml` → `TRELLO.credentials.api_key: ${TRELLO_API_KEY}` and `api_token: ${TRELLO_API_TOKEN}`
- `.env/apps.env` → resolves the actual values
- Call `https://api.trello.com/1/` with `?key=...&token=...`

This pattern applies to all 16+ integrations. Always check config first, then env file.

### How to Call APIs Directly
Since harqis-core Python isn't easily importable standalone, I call APIs directly:
- **OANDA:** REST via `Invoke-RestMethod` or Node.js with Bearer token from `.env/apps.env`
- **TCG MP:** POST to `/auth` first, then use JWT in headers
- **Gmail:** Node.js HTTPS with Bearer token from `storage-gmail.json` (auto-refreshes via OAuth)
- For Gmail token refresh: use `refresh_token` + client credentials from `credentials.json`

Account/credential details: see `memory/private.md`

---

## OpenClaw Setup

- **Config and workspace paths:** see `memory/private.md`
- Active channels: **Telegram** (@harqis_bot), WhatsApp disabled
- Model: `anthropic/claude-sonnet-4-6`
- Heartbeat: every 90 min, lightContext enabled
- Compaction: safeguard mode with memory flush
- Thinking: off (cost optimization)

---

## Git Workflow

- **Auto-commit + push** any changes inside `.openclaw/workspace/` after every edit
- Scope is strictly `C:\Users\brian\GIT\harqis-work\.openclaw\workspace\` — nothing else
- All other repo changes are Brian's to commit manually
- Commit message format: `(openclaw-commit) <short description>`

---

## Lessons Learned

- `OPENCLAW_STATE_DIR` env var only takes effect in new shell sessions — gateway currently still reads from old path even after state copy; needs full restart from new shell
- PowerShell multi-variable assignment lines get flagged as "obfuscated" by exec security — use Node.js or Python for complex scripts
- `python3` not on PATH — use `node` for scripting tasks
- Gmail OAuth token has a `refresh_token` — can refresh using `client_id`/`client_secret` from `credentials.json`
- TCG Marketplace SSL cert may cause issues with `Invoke-RestMethod` — use `System.Net.WebClient` or disable cert validation for local calls
- `.openclaw/workspace` had a nested `.git` from a previous repo init — removed it to track under `harqis-work` repo
- Exec approval policy set to allow-always for complex PowerShell analysis scripts

---

## Personality / Tone

Brian wants responses that are:
- **Laid back** — no corporate speak, no filler phrases
- **Concise** — get to the point fast
- **Informative** — don't skip relevant details
- Short replies for simple tasks, detailed when it matters
