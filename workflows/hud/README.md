# HUD Workflow

## Description

- Displays real-time data on a Windows desktop HUD via Rainmeter widgets.
- Aggregates data from Google Calendar, OANDA forex, TCG Marketplace, YNAB budgets, AppSheet (PC INVOICE table), and Elasticsearch logs.
- 15 scheduled Celery tasks push data to the desktop feed at various intervals.
- Tasks use the decorator chain: `@SPROUT.task` → `@log_result` → `@init_meter` → `@feed`.

## Queues

Most tasks run on the `hud` queue (auto-routed via `SPROUT.conf.task_routes` for `workflows.hud.tasks.*`). One exception: `take_screenshots_for_gpt_capture` is pinned to `peon` via an explicit `options.queue` override in the beat entry. All HUD tasks carry `options.os = ["windows"]` since they write Rainmeter `.ini` files and use Win32 APIs.

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
| `show_daily_radar` | 08:00 / 12:00 / 16:00 / 20:00 / 00:00 daily | DAILY RADAR — combines AGENTS_IDEAS #1/#3/#4/#12/#17 into one briefing. **Input sweep**: Gmail (last 8h, GOOGLE_GMAIL scope), Calendar (today, GOOGLE_APPS), Google Tasks (open, GOOGLE_TASKS), Trello (open cards), Jira (tickets updated in window), GitHub PRs involving me (last 8h, `involves:@me`), OwnTracks last location (context only), ES failed-jobs, plus the DESKTOP LOGS dump.txt tail. Sent to Claude Sonnet 4.6 for synthesis. Output preserves section breaks (`wrap_preserving_breaks`, wrap width 65) so bullets and `===` rules survive into the HUD. Width matches DESKTOP LOGS (`width_multiplier=2.25`); height fixed at `ItemLines=16`; marquee scrolls anything beyond. Single DUMP header link. `play_sound=True`. `[START]`/`[END]` bracket the 8h window. Visible during WORK and ORGANIZE calendar blocks. Queue: `hud`. |

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
| `tasks/hud_radar.py` | `show_daily_radar` |
| `tasks/daily_radar_agent.py` | Data-gathering helpers consumed by `show_daily_radar` (Gmail / Calendar / Tasks / Trello / Jira / ES collectors, prompt formatter, and `wrap_preserving_breaks` output wrapper) |
| `tasks/sections.py` | HUD section layout helpers |
| `prompts/daily_radar.md` | DAILY RADAR synthesis prompt (combines ideas #1, #3, #4, #12, #17 from `data/AGENTS_IDEAS.md`) |
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
| `trello` | Open cards on the agents kanban board(s) — feeds DAILY RADAR notification triage |

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

### DAILY RADAR architecture

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
       │             │  Anthropic Claude Sonnet 4.6 │
       │             │  (prompts/daily_radar.md +   │
       │             │   inputs block)              │
       │             └─────────────┬────────────────┘
       │                           │ briefing
       │                           ▼
       │          DAILY RADAR/dump.txt (prepended, auto-scrolling marquee)
       │
       └─── 4h cron tick (run-job--show_daily_radar)
```

Behavior:

- **Cadence:** every 4 hours (`crontab(hour='*/4', minute=0)`).
- **Analysis window:** last 8 hours of email / failed jobs / Jira updates (configurable via `window_hours`).
- **Sound:** `play_sound=True` — Rainmeter beeps on each update.
- **Scroll:** `MeasureLuaScriptScroll` (auto-scrolling marquee, identical to DESKTOP LOGS).
- **Width:** `width_multiplier=2.25` — matches DESKTOP LOGS so the two pinned widgets line up side by side.
- **Height:** FIXED at `DAILY_RADAR_MAX_HUD_LINES` (30) — tall enough to keep ~5 of the radar's 7 content sections on-screen at once. Earlier defaults (15 like MOUSE BINDINGS, 22 mid-iteration) hid too much of the briefing behind the marquee. The marquee still scrolls anything past 30 lines so longer briefings don't grow the widget. **Note**: this widget sets BOTH `Variables.ItemLines` (sizes the meter background) AND `Variables.MaxLines` (controls how many lines `TextCycle.lua` renders at once, default 16). Other widgets only set `ItemLines` and inherit the Lua-script default for the marquee window. If you copy this widget as a template, keep them in sync — setting only `ItemLines` inflates the background while the visible scrolling text stays capped at 16.
- **Wrap width:** 65 chars, tuned to the 2.25 column width.
- **Readability:** `wrap_preserving_breaks` keeps the prompt's section structure intact (each `===` rule, blank-line break, and bullet line survives — the previous `wrap_text` flattened everything to one paragraph).
- **Header links:** one only — `DUMP`, opens the rendered `DAILY RADAR/dump.txt` for inspection.
- **Resilience:** every collector is wrapped in its own try/except so a missing Trello board, expired OAuth token, or offline ES does not break the render — the affected section renders `"<source> unavailable: <reason>"` instead. The Trello collector specifically guards against non-list responses from `@deserialized` (regression: `'Response' object is not subscriptable`).
- **Cost:** Sonnet 4.6 pinned in the beat schedule (`model="claude-sonnet-4-6"`). Sonnet's stronger synthesis is worth the cost for a once-per-shift briefing; if cost becomes a concern, pass `model="claude-haiku-4-5-20251001"` from the beat kwargs.

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
