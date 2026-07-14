# HUD Workflow

## Description

- Displays real-time data on a Windows desktop HUD via Rainmeter widgets.
- Aggregates data from Google Calendar, OANDA forex, TCG Marketplace, YNAB budgets, AppSheet (PC INVOICE table), and Elasticsearch logs.
- 15 scheduled Celery tasks push data to the desktop feed at various intervals.
- Tasks use the decorator chain: `@SPROUT.task` → `@log_result` → `@init_meter` → `@feed`.

## Queues

Most tasks run on the `hud` queue (auto-routed via `SPROUT.conf.task_routes` for `workflows.hud.tasks.*`). One exception: `take_screenshots_for_gpt_capture` is pinned to `peon` via an explicit `options.queue` override in the beat entry. All HUD tasks carry `options.os = ["windows"]` since they write Rainmeter `.ini` files and use Win32 APIs.

**Data-only fallback twins** (`workflows.hud.tasks.hud_data_only.*`) are the exception to the Windows pinning: they run on the always-on host's `host` queue (a more-specific route declared above the `hud` catch-all in `workflows/config.py`) so a HUD task's `@feed` dump + `@log_result` ES record survive while the Windows box is offline. See [Data-only fallback (host)](#data-only-fallback-host) below.

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
| `show_pc_daily_sales` | Every 4 hours | PC DAILY SALES — sums `TOTAL PRICE` per `DATE` from the AppSheet `INVOICE` table for the last 60 days, grouped by month with a 24-dash separator. Same width as OANDA ACCOUNT; height shows 10 rows at a time, the rest scrolls. Queue: `hud`. |
| `show_api_costs` | Every 2 hours | TOKEN BURN — trailing 3-month LLM API spend grouped per month → service → model. Anthropic from the admin usage API (`ANTHROPIC_ADMIN_KEY`); OpenAI / Gemini stubbed at zero until cost endpoints exist. Service section omitted when its monthly total is 0. Queue: `hud`. |
| `show_ai_helper` | Daily at midnight | AI helper widget initialization |
| `get_schedules` | Every 4 hours | Upcoming calendar schedule |
| `show_daily_radar_data_only` | 08:00 / 12:00 / 16:00 / 20:00 (host) | **Data-only fallback twin** of `show_daily_radar`. Runs on the `host` queue and writes the briefing to the `hud-data-only-*` feed + ES **only when** the Windows worker hasn't rendered the radar within ~12h+10min (the overnight inter-fire gap + grace). No Rainmeter render. Gated on the original's `@log_result` heartbeat. Queue: `host`. |
| `export_hermes_radar_snapshot` | Every 15 min (host) | Reads Hermes' local Telegram assistant history and scheduled-delivery audit, removes user/tool/reasoning data plus credentials, identifiers, and local paths, then atomically writes `hermes-radar.json` to the shared feed. No Telegram poll and no LLM. Queue: `host`. |
| `refresh_hermes_radar` | :05 / :20 / :35 / :50 (Windows) | Rerenders `RECENT HERMES PUSHES` from the shared snapshot, newest first, last 8h, max 10. Preserves the last four-hour synthesis and valid push block when the snapshot is stale/unavailable. No LLM. Queue: `hud`. |
| `show_daily_radar` | 08:00 / 12:00 / 16:00 / 20:00 daily | **HERMES RADAR** deep synthesis. Keeps the established task name and `DAILYRADAR` Rainmeter folder for feed/heartbeat/forwarder compatibility, while the visible title and Express target are HERMES RADAR. Combines AGENTS_IDEAS #1/#3/#4/#12/#17 using the existing 8-hour source sweep and Haiku 4.5, then composes it below the latest sanitized push section. Queue: `hud`. |

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
| `tasks/hud_radar.py` | `show_daily_radar` (four-hour synthesis render), `refresh_hermes_radar` (15-minute JSON-only render) |
| `tasks/hermes_radar_export.py` | `export_hermes_radar_snapshot` — host-safe scheduled exporter |
| `tasks/daily_radar_agent.py` | Data-gathering helpers consumed by `collect_daily_radar` (Gmail / Calendar / Tasks / Trello / Jira / GitHub / OwnTracks / ES collectors, prompt formatter, and `wrap_preserving_breaks` output wrapper) |
| `tasks/hud_data_only.py` | Data-only fallback twins routed to the `host` queue (`show_daily_radar_data_only`, …). Win32-free — imported outside the `__init__.py` win32 guard. |
| `collectors/daily_radar.py` | `collect_daily_radar` — win32-free HERMES RADAR synthesis path (legacy module name retained) shared by the Windows render task and host twin. |
| `collectors/hermes_pushes.py` | Sanitization, Hermes state/cron audit collection, atomic shared snapshot I/O, freshness states, dedupe/limit, and HERMES RADAR composition. |
| `fallback.py` | `windows_handled_recently` + the `fallback_gate` decorator — read the `@log_result` heartbeat so a twin runs only when the Windows original went stale. Fails open. |
| `tasks/sections.py` | HUD section layout helpers |
| `prompts/daily_radar.md` | HERMES RADAR synthesis prompt (legacy filename retained; combines ideas #1, #3, #4, #12, #17 from `data/AGENTS_IDEAS.md`) |
| `prompts/desktop_analysis.md` | DESKTOP LOGS evidence-only activity analysis prompt |

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

1. **15-minute notification path (no LLM):** the host reads local Hermes
   assistant/session state plus cron output/status, keeps only Telegram-bound
   outbound content, sanitizes and deduplicates it, and atomically writes
   `<shared feed>/hermes-radar.json`. Windows rerenders at :05/:20/:35/:50 so
   the shared drive has time to sync.
2. **Four-hour synthesis path:** `show_daily_radar` keeps its established task,
   feed marker, ES heartbeat, fallback gate, and `DAILYRADAR` folder. It runs the
   existing source sweep at 08:00/12:00/16:00/20:00 and places the result under
   `DAILY BRIEFING`.

The exporter never calls `getUpdates`, never connects Windows to
`~/.hermes/state.db`, and never writes a partial/failed snapshot. Snapshot read
states are explicit: fresh, stale after 35 minutes, or unavailable. Stale data
remains visible with a warning; unavailable refreshes preserve the last valid
push block and synthesis.

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

- **Cadence:** pushes export every 15 minutes and render five minutes later; deep synthesis runs at 08:00, 12:00, 16:00, and 20:00.
- **Push scope:** last 8 hours, newest first, maximum 10; interactive assistant replies plus Telegram-configured cron outputs and delivery/job failures. User messages, tool traces, reasoning, system prompts, secrets, IDs, raw local paths, and looped radar dumps are excluded.
- **Analysis window:** last 8 hours of email / failed jobs / Jira updates (configurable via `window_hours`).
- **Sound:** the four-hour synthesis uses `play_sound=True`; 15-minute notification-only refreshes stay silent.
- **Scroll:** `MeasureLuaScriptScroll` (auto-scrolling marquee, identical to DESKTOP LOGS).
- **Width:** `width_multiplier=2.25` — matches DESKTOP LOGS so the two pinned widgets line up side by side.
- **Height:** fixed at `DAILY_RADAR_MAX_HUD_LINES` (16). The widget sets both `Variables.ItemLines` and `Variables.MaxLines`; the marquee scrolls content beyond that stable footprint.
- **Wrap width:** 65 chars, tuned to the 2.25 column width.
- **Readability:** `wrap_preserving_breaks` keeps the prompt's section structure intact (each `===` rule, blank-line break, and bullet line survives — the previous `wrap_text` flattened everything to one paragraph).
- **Header links:** one only — `DUMP`, opens the established `DAILYRADAR/dump.txt` compatibility path.
- **Resilience:** every collector is wrapped in its own try/except so a missing Trello board, expired OAuth token, or offline ES does not break the render — the affected section renders `"<source> unavailable: <reason>"` instead. The Trello collector specifically guards against non-list responses from `@deserialized` (regression: `'Response' object is not subscriptable`).
- **Cost:** the 15-minute path makes zero model calls. The four-hour synthesis pins `claude-haiku-4-5-20251001` in the beat schedule.

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

## Data-only fallback (host)

HUD render tasks run only on the Windows `hud` queue. When that box is offline the task body never executes, so the `@feed` dump and `@log_result` Elasticsearch record are lost — **not** because the sinks are Windows-bound (`@log_result` writes to a network ES service; `@feed` resolves per-OS and the host has the same Google-Drive LOGS mount via `DESKTOP_PATH_FEED_DARWIN`), but because nothing runs. *Data-only twins* close that gap by running the same data computation on the always-on host, skipping the Rainmeter render.

The split (built per task by the `/create-data-only-from-hud` skill):

```
collectors/<slug>.py   collect_<slug>()  ── win32-free data path (fetch + dump + metrics)
        ▲                       ▲
        │ calls                 │ calls
hud_<slug>.py            hud_data_only.py
show_<slug>              <fn>_data_only            ── @SPROUT.task / @fallback_gate / @log_result / @feed
 (Windows: hud queue,     (host queue, no render)
  collector + render)
```

- **Single source of truth:** both the Windows render task and the host twin call the same `collect_<slug>()`, so they never drift.
- **Fallback-only gating:** `@fallback_gate(original_task_name, max_staleness_secs)` (in `fallback.py`) reads the original's `@log_result` heartbeat doc (`harqis-elastic-logging`, keyed by `name`, field `date`). If the original ran within the staleness window, the twin short-circuits — **no feed block, no twin ES doc** — so healthy-Windows cycles produce zero duplicates. Staleness = the original's largest inter-fire gap + grace; the twin engages one cadence after Windows genuinely stops. Fails **open** (ES down/missing doc → run the twin).
- **Routing:** twins live at `workflows.hud.tasks.hud_data_only.*` and are routed to `host` by a rule declared **above** the `workflows.hud.tasks.*` catch-all in `workflows/config.py` (else the catch-all would send them to `hud`). Beat entries are grouped at the bottom of the existing `WORKFLOWS_HUD` dict in `tasks_config.py` — kept in that one dict (not a separate `WORKFLOWS_HUD_DATA_ONLY`) so `frontend/generate_registry.py`, which reads only the first `run-job--*` dict per file, still catalogues them.
- **Distinct feed file:** twins write `hud-data-only-YYYYMMDD.txt` (the Windows tasks write `hud-logs-*`), so host and Windows dumps never interleave.
- **Eligibility:** only API/data-backed tasks get a twin. Desktop-capture tasks (`show_mouse_bindings`, `get_desktop_logs`, screenshots, `build_summary_mouse_bindings`, `show_hud_profiles`) read Windows-local state and stay Windows-only. The HERMES RADAR compatibility twin (`show_daily_radar_data_only`) runs the full 8-source sweep minus the DESKTOP LOGS section (that dump.txt is Windows-local; `collect_inputs` reads it as empty on the host).

Manually trigger a twin (bypassing the gate) for testing: pass `force=True`.

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
