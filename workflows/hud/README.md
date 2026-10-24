# HUD Workflow

## Description

- Supplies the portable Second Brain web HUD at `/second-brain`; Rainmeter rendering is deprecated and opt-in (`HARQIS_LEGACY_RAINMETER=1`).
- Aggregates data from Google Calendar, OANDA forex, TCG Marketplace, YNAB budgets, AppSheet (PC INVOICE table), and Elasticsearch logs.
- 20 enabled schedule entries cover display collectors and support jobs; see the [source audit](../../docs/info/HUD-SOURCE-INVENTORY.md).
- Tasks use the decorator chain: `@SPROUT.task` → `@log_result` → `@init_meter` → `@feed`.
- Current HUD panels also include `@capture_hud_projection` immediately before
  `@init_meter`. Successful return payloads are redacted and capped before being
  projected to Elasticsearch for read-only Second Brain adapters; projection
  failure never interrupts collection. The full dump text and safe header links survive in the portable return payload.

## Queues

API-backed Calendar, finance, forex, Jira, API costs, job summaries and radar run on `host`, with matching Beat and manual-call routes. These collectors register on every platform and publish portable text without a Rainmeter installation. Desktop inspection, mouse/iCUE, bindings and profile work retain Windows affinity. TCG orders and sell-cart also stay on Windows: they export QR files and may add items to carts, respectively.

There are 20 schedules: 12 `host`, seven `hud`, and one screenshot capture on `peon`. Only the host runs Celery Beat. A task is consumed by one worker subscribed to its queue; `os` metadata is descriptive, not a scheduler constraint.

The radar data-only twin remains importable for compatibility but is no longer scheduled, avoiding duplicate synthesis now that the original runs on the host.

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `show_forex_account` | Every 15 min (weekdays) | OANDA forex account summary |
| `show_tcg_orders` | Every hour | TCG Marketplace open orders |
| `show_tcg_sell_cart` | Sundays at midnight | Match my listings to want-to-buy bids within `discount_threshold_pct` and queue them in the seller's sell cart for manual fulfilment. Multiprocess one worker per listing. |
| `show_jira_board` | Weekdays every hour | Pull In-Review / In-Progress / Ready / In-Analysis tickets from a Jira Software board (rapidView=`board_id`) and render them as a 4-section HUD widget. |
| `get_desktop_logs` | Every 5 min | AI analysis of desktop activity logs |
| `take_screenshots_for_gpt_capture` | Every 10 min | Desktop screenshot capture. Queue: `peon`. |
| `show_calendar_information` | Every 15 min | Google Calendar events for today |
| `get_failed_jobs` | Every 15 min | Failed Celery task list |
| `show_mouse_bindings` | Every 60 sec | Mouse shortcut bindings display |
| `build_summary_mouse_bindings` | Daily at 1am | Summary of daily mouse bindings |
| `show_hud_profiles` | Daily at midnight | Active iCUE/Rainmeter HUD profiles |
| `show_ynab_budgets_info` | Every 4 hours | YNAB budget balances |
| `show_pc_daily_sales` | Every 2 hours | PC DAILY SALES — sums `TOTAL PRICE` per `DATE` from the AppSheet `INVOICE` table for the last 60 days, grouped by month with a 24-dash separator. Same width as OANDA ACCOUNT; height shows 10 rows at a time, the rest scrolls. Queue: `host`. |
| `show_api_costs` | Every 30 minutes | TOKEN BURN — trailing 3-month LLM API spend grouped per month → service → model. Anthropic from the admin usage API (`ANTHROPIC_ADMIN_KEY`); OpenAI / Gemini stubbed at zero until cost endpoints exist. Service section omitted when its monthly total is 0. Queue: `host`. |
| `show_ai_helper` | Daily at midnight | AI helper widget initialization |
| `get_schedules` | Every 4 hours | Upcoming calendar schedule |
| `export_hermes_radar_snapshot` | Hourly at :00 (host) | Reads Hermes' scheduled-delivery audit, keeps only Telegram-bound jobs from the last 12h, removes credentials, identifiers, and local paths, then atomically writes `hermes-radar.json` to the shared feed. Conversational replies are never exported. No Telegram poll and no LLM. Queue: `host`. |
| `refresh_hermes_radar` | Hourly at :05 (host) | Rerenders the shared snapshot as a newest-first, timestamped mirror of delivered scheduled Telegram updates from the last 12h. Multiline structure is preserved; secrets, emoji, and unsupported Unicode are removed. No LLM. Queue: `host`. |
| `show_daily_radar` | 08:00 / 12:00 / 16:00 / 20:00 daily | **HERMES RADAR** deep synthesis. Keeps the established task name and `DAILYRADAR` Rainmeter folder for feed/heartbeat/forwarder compatibility. The 8-hour Haiku synthesis continues into `feed_text` for HFL/legacy consumers, while the visible dump remains the 12-hour scheduled-delivery mirror. Queue: `host`. |

## Task Files

| File | Tasks |
|------|-------|
| `tasks/hud_forex.py` | `show_forex_account` |
| `tasks/hud_tcg.py` | `show_tcg_orders`, `show_tcg_sell_cart` |
| `tasks/hud_jira.py` | `show_jira_board` |
| `tasks/hud_gpt.py` | `get_desktop_logs`, `take_screenshots_for_gpt_capture` |
| `tasks/hud_logs.py` | `get_failed_jobs`, `get_schedules` |
| `tasks/hud_calendar.py` | `show_calendar_information` |
| `tasks/hud_utils.py` | `show_mouse_bindings`, `build_summary_mouse_bindings`, `show_hud_profiles`, `show_ai_helper` |
| `tasks/hud_finance.py` | `show_ynab_budgets_info`, `show_pc_daily_sales` |
| `tasks/hud_api_costs.py` | `show_api_costs` |
| `tasks/hud_radar.py` | `show_daily_radar` (four-hour synthesis feed), `refresh_hermes_radar` (hourly JSON-only render) |
| `tasks/hermes_radar_export.py` | `export_hermes_radar_snapshot` — host-safe scheduled exporter |
| `tasks/daily_radar_agent.py` | Data-gathering helpers consumed by `collect_daily_radar` (Gmail / Calendar / Tasks / Trello / Jira / GitHub / OwnTracks / ES collectors, prompt formatter, and `wrap_preserving_breaks` output wrapper) |
| `tasks/hud_data_only.py` | Data-only fallback twins routed to the `host` queue (`show_daily_radar_data_only`, …). Win32-free — imported outside the `__init__.py` win32 guard. |
| `collectors/daily_radar.py` | `collect_daily_radar` — win32-free HERMES RADAR synthesis path (legacy module name retained) shared by the Windows render task and host twin. |
| `collectors/hermes_pushes.py` | Multiline ASCII sanitization, Hermes cron audit collection, atomic shared snapshot I/O, strict 12-hour filtering, freshness states, and HERMES RADAR composition. |
| `fallback.py` | `windows_handled_recently` + the `fallback_gate` decorator — read the `@log_result` heartbeat so a twin runs only when the Windows original went stale. Fails open. |
| `tasks/sections.py` | HUD section layout helpers |
| `prompts/daily_radar.md` | HERMES RADAR synthesis prompt (legacy filename retained; combines ideas #1, #3, #4, #12, #17 from `data/AGENTS_IDEAS.md`) |
| `prompts/desktop_analysis.md` | DESKTOP LOGS evidence-only activity analysis prompt |

## Manual and compatibility tasks

- `broadcast_reload_config` (`tasks/broadcast_reload.py`) is an ad-hoc
  `workers_broadcast` fanout entry point that records a lightweight HUD-side
  configuration reload signal on every subscribed worker. It is not in Beat.
- `get_events_world_check` (`tasks/hud_gpt.py`) builds the GPT/world-events HUD
  check for the requested countries and timezone. It remains a callable Celery
  task but is not currently scheduled.
- `show_ahk_bindings` (`tasks/hud_utils.py`) parses the configured AutoHotkey
  macro file and renders the AHK bindings widget. It is Windows/Rainmeter-only
  and not currently scheduled; supply `ahk_path` instead of relying on the
  legacy local default when invoking it on another host.

## App Dependencies

| App | Used For |
|-----|---------|
| `oanda` | Forex account balance and open trades |
| `tcg_mp` | Open orders display |
| `google_apps` | Calendar events and schedules |
| `ynab` | Budget balances by currency (PHP, SGD) |
| `appsheet` | PC INVOICE table — gross daily sales aggregation |
| `rainmeter` | Desktop HUD skin rendering |
| `desktop` | Screenshot capture, log reading |
| `open_ai` / `antropic` | Log analysis and AI helper |
| `trello` | Open cards on the agents kanban board(s) — feeds HERMES RADAR notification triage |

## DTOs / Constants

| Name | File | Description |
|------|------|-------------|
| `AppExe` | `constants.py` | Enum of Windows app executables (Docker, Chrome, PyCharm, etc.) |
| `Profile` | `constants.py` | Enum of iCUE/HUD profiles (BASE, BROWSER, MARKDOWN, CODING, etc.) |
| `APP_TO_PROFILE` | `constants.py` | Dict mapping `AppExe` to `Profile` |

## Prompt Templates

AI tasks use markdown prompts from `workflows/hud/prompts/` (loaded via `from workflows.hud.prompts import load_prompt`):

- `desktop_analysis.md` — Prompt for log analysis (`get_desktop_logs`). Evidence-only summarisation of the rolling activity log + screenshots.
- `daily_radar.md` — Prompt for `show_daily_radar`. Combines five productivity ideas (`#1` desktop context, `#3` overlooked commitments, `#4` email priority, `#12` notification triage, `#17` daily command center from `data/AGENTS_IDEAS.md`) into a single 8-hour briefing with `TOP 3 PRIORITIES`, `OVERLOOKED COMMITMENTS`, `EMAIL PRIORITY`, `NOTIFICATION TRIAGE`, `DESKTOP CONTEXT`, and `SUGGESTED FIRST MOVE` sections.

### HERMES RADAR architecture

The panel has two independent paths that meet only at render time:

1. **Hourly notification path (no LLM):** the host reads local Hermes cron
   output/status, keeps only Telegram-bound scheduled deliveries, redacts
   sensitive values, converts the content to ASCII while
   preserving line structure, and atomically writes
   `<shared feed>/hermes-radar.json`. The host refreshes at :05 so the shared
   drive has five minutes to sync after the :00 export.
2. **Four-hour synthesis path:** `show_daily_radar` keeps its established task,
   feed marker, ES heartbeat, fallback gate, and `DAILYRADAR` folder. It runs the
   existing source sweep at 08:00/12:00/16:00/20:00 and writes the result to the
   synthesis-only feed contract; it does not replace the visible message mirror.

The exporter never calls `getUpdates`, never exports conversational session
history, and never writes a partial/failed snapshot. Snapshot read
states are explicit: fresh, stale after 75 minutes, or unavailable. The Windows
loader reapplies the 12-hour cutoff, so stale or delayed shared-drive data
cannot keep older replies visible. An unavailable snapshot shows an explicit
notice instead of preserving an unbounded prior render.

```
                         ┌──────────────────────────────┐
       ┌────────────────►│  workflows/hud/tasks/        │
       │                 │   hud_radar.py               │◄──── @init_meter (Rainmeter)
       │                 │   show_daily_radar           │
       │                 └─────────────┬────────────────┘
       │                               │ calls
       │                               ▼
       │  ┌──────────────────────────────────────────────────────────────┐
       │  │  workflows/hud/tasks/daily_radar_agent.py                    │
       │  │                                                              │
       │  │  collect_inputs(...) → {                                     │
       │  │    desktop_activity_log,                                     │  ◄── reads DESKTOPLOGS/dump.txt
       │  │    gmail_recent,                                             │  ◄── ApiServiceGoogleGmail (8h)
       │  │    calendar_today,                                           │  ◄── ApiServiceGoogleCalendarEvents
       │  │    google_tasks_open,                                        │  ◄── ApiServiceGoogleTasks
       │  │    trello_open_cards,                                        │  ◄── ApiServiceTrelloBoards
       │  │    jira_recent_updates,                                      │  ◄── ApiServiceJiraIssues (JQL: updated >= -8h)
       │  │    github_prs_involving_me,                                  │  ◄── ApiServiceGitHubRepos.search_issues (involves:@me)
       │  │    last_location,                                            │  ◄── ApiServiceOwnTracksLocations.get_last
       │  │    es_failed_jobs,                                           │  ◄── get_index_data(LOGGING_INDEX)
       │  │  }                                                           │
       │  │  format_inputs_as_prompt_text(...) → flattened delimiter text│
       │  └───────────────────────────┬──────────────────────────────────┘
       │                              │
       │                              ▼
       │             ┌──────────────────────────────┐
       │             │  Anthropic Claude Haiku 4.5  │
       │             │  (prompts/daily_radar.md +   │
       │             │   inputs block)              │
       │             └─────────────┬────────────────┘
       │                           │ briefing
       │                           ▼
       │          HERMES RADAR (DAILYRADAR/dump.txt compatibility path)
       │
       └─── 4h cron tick (run-job--show_daily_radar)
```

Behavior:

- **Cadence:** scheduled deliveries export hourly at :00 and render at :05; deep synthesis runs at 08:00, 12:00, 16:00, and 20:00.
- **Push scope:** delivered Telegram-configured cron outputs from the last 12 hours, newest first. Conversational replies and delivery/job failures are excluded, along with user messages, tool traces, reasoning, system prompts, secrets, IDs, raw local paths, emoji, unsupported Unicode, and looped radar dumps.
- **Analysis window:** last 8 hours of email / failed jobs / Jira updates (configurable via `window_hours`).
- **Sound:** the four-hour synthesis uses `play_sound=True`; hourly notification-only refreshes stay silent.
- **Scroll:** `MeasureLuaScriptScroll` (auto-scrolling marquee, identical to DESKTOP LOGS). HERMES RADAR sets a skin-local `WrapAt` width so long physical dump lines become bounded visual rows before the 19-row marquee window is selected.
- **Width:** `width_multiplier=2.25` — matches DESKTOP LOGS so the two pinned widgets line up side by side.
- **Height:** fixed at `DAILY_RADAR_MAX_HUD_LINES` (19), approximately 20% more visible lines than the previous 16-line footprint. The widget sets both `Variables.ItemLines` and `Variables.MaxLines`; the marquee scrolls content beyond that stable footprint.
- **Viewport clipping:** the content meter subtracts its 70 px header offset and a 14 px footer from the skin height, preventing wrapped text from painting over adjacent HUD content during initial load.
- **Wrap width:** 65 chars, tuned to the 2.25 column width.
- **Readability:** scheduled deliveries preserve paragraph and list breaks. Smart punctuation is converted to ASCII where possible; remaining non-ASCII characters and emoji are removed before the shared snapshot is written. The content meter uses a 22 px left inset and a matching width reduction to preserve its right margin.
- **Header links:** one only — `DUMP`, opens the established `DAILYRADAR/dump.txt` compatibility path.
- **Resilience:** every collector is wrapped in its own try/except so a missing Trello board, expired OAuth token, or offline ES does not break the render — the affected section renders `"<source> unavailable: <reason>"` instead. The Trello collector specifically guards against non-list responses from `@deserialized` (regression: `'Response' object is not subscriptable`).
- **Cost:** the hourly path makes zero model calls. The four-hour synthesis pins `claude-haiku-4-5-20251001` in the beat schedule.

### Source registry (extensibility)

Data sources are declared in `daily_radar_agent.py::SOURCE_REGISTRY`. Each entry is a `SourceSpec` dataclass binding a `name` (the lookup key used in the beat schedule's `sources=[...]` list) to its `default_cfg`, `collector`, `formatter`, `payload_key`, and `prompt_marker`. The radar's three orchestrating functions — `collect_inputs`, `format_inputs_as_prompt_text`, and `summarise_inputs` — all iterate the registry instead of carrying per-source branches.

**To add a new source** (e.g. Notion recent edits):

1. Write `collect_notion_recent(cfg_id, hours, **params) -> {pages, error}` in `daily_radar_agent.py`. MUST be fail-soft — return the error string, never raise.
2. Write `_format_notion_pages(section) -> str` next to it. MUST handle `error`, empty, and populated payloads.
3. Append a `SourceSpec` to the registry in `_register_default_sources()` at the bottom of the file.
4. Add the source name to `sources=[...]` in the beat schedule (or pass it from a custom call).
5. Add one section block to `prompts/daily_radar.md` so the LLM knows the input exists and what to do with it.
6. Add a unit test for the formatter.

`collect_inputs`, `show_daily_radar`, the beat-schedule signature, and the test fixtures stay untouched.

**Per-source tuning without code edits:**

- `source_overrides={"gmail": "GOOGLE_GMAIL_WORK"}` — redirect a single source to a different `apps_config.yaml` key.
- `source_params={"owntracks": {"user": "brian"}}` — pass source-specific kwargs to a collector. Merged on top of the spec's `default_params`.
- Drop a name from `sources` to disable that feed; reorder to change which sections the LLM weighs first.

## Data-only fallback (compatibility)

`hud_data_only.show_daily_radar_data_only` and its heartbeat gate remain available for older callers. Its Beat entry has been removed: the primary radar collector now runs on the always-on host, with desktop-local inputs omitted there. Do not re-enable the twin alongside the primary host schedule. New API widgets should use a single portable collector on `host`.

## Running

```sh
# Start a worker for the hud queue
celery -A workflows.config worker --loglevel=info -Q hud

# Trigger a task manually (via Celery CLI or Flower)
celery -A workflows.config call workflows.hud.tasks.hud_calendar.show_calendar_information
```

## Notes

- `show_mouse_bindings` reads the active foreground window to set the appropriate iCUE/Rainmeter profile.
- `get_desktop_logs` sends activity log content to GPT/Claude for summarization.
- HUD feed data is written to `DESKTOP_PATH_FEED` (env var) and picked up by Rainmeter.

## Manifesto alignment

See [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) and [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md). The same metadata is persisted on each beat entry's `'manifesto'` key in `tasks_config.py`.

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `show_forex_account` | capture | area | `rainmeter:FOREX_ACCOUNT` | `es_log+hud_widget` | `False` |
| `show_tcg_orders` | capture | area | `rainmeter:TCG_ORDERS` | `es_log+hud_widget` | `False` |
| `show_tcg_sell_cart` | capture | area | `rainmeter:TCG_SELL_CART` | `es_log+hud_widget` | `False` |
| `show_jira_board` | capture+distill | area | `rainmeter:JIRA_BOARD` | `es_log+hud_widget` | `True` |
| `get_desktop_logs` | distill+express | area | `rainmeter:DESKTOP_LOGS` | `es_log+hud_widget` | `True` |
| `take_screenshots_for_gpt_capture` | capture | area | `file:screenshots` | `es_log+file` | `True` |
| `show_calendar_information` | capture+distill | area | `rainmeter:CALENDAR_INFO` | `es_log+hud_widget` | `True` |
| `get_failed_jobs` | capture | area | `rainmeter:FAILED_JOBS` | `es_log+hud_widget` | `False` |
| `show_mouse_bindings` | capture | area | `rainmeter:MOUSE_BINDINGS` | `es_log+hud_widget` | `True` |
| `build_summary_mouse_bindings` | distill | area | `rainmeter:MOUSE_BINDINGS` | `es_log+hud_widget` | `True` |
| `show_hud_profiles` | capture | area | `rainmeter:HUD_PROFILES` | `es_log+hud_widget` | `False` |
| `show_ynab_budgets_info` | capture | area | `rainmeter:YNAB_BUDGETS` | `es_log+hud_widget` | `False` |
| `show_pc_daily_sales` | capture+distill | area | `rainmeter:PC_DAILY_SALES` | `es_log+hud_widget` | `False` |
| `show_api_costs` | capture+distill | area | `rainmeter:API_COSTS` | `es_log+hud_widget` | `False` |
| `show_ai_helper` | organize | area | `rainmeter:AI_HELPER` | `es_log+hud_widget` | `False` |
| `show_daily_radar` | distill+express | area | `rainmeter:HERMES_RADAR` | `es_log+hud_widget` | `True` |
| `export_hermes_radar_snapshot` | capture+organize | area | `shared-feed:hermes-radar.json` | `sanitized_json_snapshot` | `False` |
| `refresh_hermes_radar` | express | area | `rainmeter:HERMES_RADAR` | `hud_widget` | `False` |
| `get_schedules` | capture | area | `rainmeter:SCHEDULES` | `es_log+hud_widget` | `True` |
