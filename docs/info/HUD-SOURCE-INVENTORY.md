# HUD source inventory

Source audit: 2026-10-24. Active means a live dictionary entry in `workflows/hud/tasks_config.py`, merged by `workflows/config.py`; it does not claim a worker is currently online. No source tasks were executed for this audit.

| Panel | Collector / compatibility adapter | Integrations in source module | Legacy visibility | Active schedule |
|---|---|---|---|---|
| TOKEN BURN | `hud_api_costs.show_api_costs` | antropic, google_apps | [ScheduleCategory.ORGANIZE, ScheduleCategory.FINANCE] | crontab(minute='*/30') |
| CALENDAR INFO | `hud_calendar.show_calendar_information` | google_apps | Always | crontab(minute='15,30,45,00') |
| BUDGETING INFO | `hud_finance.show_ynab_budgets_info` | appsheet, google_apps, ynab | [ScheduleCategory.ORGANIZE] | crontab(hour='*/1', minute=0) |
| PC DAILY SALES | `hud_finance.show_pc_daily_sales` | appsheet, google_apps, ynab | [ScheduleCategory.FINANCE, ScheduleCategory.ORGANIZE] | crontab(hour='*/2', minute=0) |
| OANDA ACCOUNT | `hud_forex.show_forex_account` | google_apps, oanda | [ScheduleCategory.FINANCE] | crontab(day_of_week='mon,tue,wed,thu,fri', minute='*/15')<br>crontab(day_of_week='sat', hour=0, minute=0) |
| DESKTOP LOGS | `hud_gpt.get_desktop_logs` | antropic, google_apps | [ScheduleCategory.PINNED] | crontab(minute=5) |
| GPT INFO | `hud_gpt.get_events_world_check` | antropic, google_apps | [ScheduleCategory.WORK] | Manual / no active Beat entry |
| JIRA BOARD | `hud_jira.show_jira_board` | google_apps, jira | [ScheduleCategory.WORK] | crontab(day_of_week='mon-fri', minute=0) |
| FAILED JOBS TODAY | `hud_logs.get_failed_jobs` | google_apps | Always | crontab(minute='*/15') |
| CELERY SPROUTS | `hud_logs.get_schedules` | google_apps | [ScheduleCategory.DEACTIVATED] | crontab(hour='0,4,8,12,16,20', minute=0) |
| HERMES RADAR | `hud_radar.show_daily_radar` | google_apps | [ScheduleCategory.PINNED] | crontab(hour='8,12,16,20', minute=0) |
| HERMES RADAR | `hud_radar.refresh_hermes_radar` | google_apps | [ScheduleCategory.PINNED] | crontab(minute=5) |
| TCG ORDERS | `hud_tcg.show_tcg_orders` | google_apps, scryfall, tcg_mp | [ScheduleCategory.PLAY] | crontab(minute=0) |
| TCG SELL CART | `hud_tcg.show_tcg_sell_cart` | google_apps, scryfall, tcg_mp | [ScheduleCategory.PLAY] | crontab(day_of_week='fri,sun,sat', hour='1,8,12,20', minute=0) |
| HUD PROFILES | `hud_utils.show_hud_profiles` | google_apps | Always | crontab(hour='00', minute=0) |
| MOUSE BINDINGS | `hud_utils.show_mouse_bindings` | google_apps | [ScheduleCategory.ORGANIZE, ScheduleCategory.WORK] | timedelta(seconds=60) |
| AGENTS CORE | `hud_utils.show_ai_helper` | google_apps | Always | crontab(hour='0', minute=0) |
| AHK BINDINGS | `hud_utils.show_ahk_bindings` | google_apps | Always | Manual / no active Beat entry |
| SECOND BRAIN | `second_brain.render_second_brain_rainmeter` | google_apps | [ScheduleCategory.PINNED] | Manual / no active Beat entry |

## All enabled HUD schedule entries

| Entry | Task | Schedule | Routing / expiry |
|---|---|---|---|
| `run-job--show_forex_account--on` | `workflows.hud.tasks.hud_forex.show_forex_account` | `crontab(day_of_week='mon,tue,wed,thu,fri', minute='*/15')` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 5}` |
| `run-job--show_forex_account--off` | `workflows.hud.tasks.hud_forex.show_forex_account` | `crontab(day_of_week='sat', hour=0, minute=0)` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 5}` |
| `run-job--show_tcg_orders` | `workflows.hud.tasks.hud_tcg.show_tcg_orders` | `crontab(minute=0)` | `{'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 30}` |
| `run-job--show_tcg_sell_cart--on` | `workflows.hud.tasks.hud_tcg.show_tcg_sell_cart` | `crontab(day_of_week='fri,sun,sat', hour='1,8,12,20', minute=0)` | `{'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 60 * 24}` |
| `run-job--show_jira_board` | `workflows.hud.tasks.hud_jira.show_jira_board` | `crontab(day_of_week='mon-fri', minute=0)` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 30}` |
| `run-job--get_desktop_logs` | `workflows.hud.tasks.hud_gpt.get_desktop_logs` | `crontab(minute=5)` | `{'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 60}` |
| `run-job--take_screenshots_for_gpt_capture` | `workflows.hud.tasks.hud_gpt.take_screenshots_for_gpt_capture` | `crontab(minute='10,20,30,40,50,00')` | `{'queue': WorkflowQueue.PEON, 'os': ['windows'], 'expires': 60 * 10}` |
| `run-job--show_calendar_information` | `workflows.hud.tasks.hud_calendar.show_calendar_information` | `crontab(minute='15,30,45,00')` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 30}` |
| `run-job--get_failed_jobs` | `workflows.hud.tasks.hud_logs.get_failed_jobs` | `crontab(minute='*/15')` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 15}` |
| `run-job--show_mouse_bindings` | `workflows.hud.tasks.hud_utils.show_mouse_bindings` | `timedelta(seconds=60)` | `{'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 2}` |
| `run-job--build_summary_mouse_bindings` | `workflows.hud.tasks.hud_utils.build_summary_mouse_bindings` | `crontab(hour='1', minute=0)` | `{'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 60}` |
| `run-job--show_hud_profiles` | `workflows.hud.tasks.hud_utils.show_hud_profiles` | `crontab(hour='00', minute=0)` | `{'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 60}` |
| `run-job--show_ynab_budgets_info` | `workflows.hud.tasks.hud_finance.show_ynab_budgets_info` | `crontab(hour='*/1', minute=0)` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 60}` |
| `run-job--show_pc_daily_sales` | `workflows.hud.tasks.hud_finance.show_pc_daily_sales` | `crontab(hour='*/2', minute=0)` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 60}` |
| `run-job--show_api_costs` | `workflows.hud.tasks.hud_api_costs.show_api_costs` | `crontab(minute='*/30')` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 15}` |
| `run-job--show_ai_helper` | `workflows.hud.tasks.hud_utils.show_ai_helper` | `crontab(hour='0', minute=0)` | `{'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 60}` |
| `run-job--show_daily_radar` | `workflows.hud.tasks.hud_radar.show_daily_radar` | `crontab(hour='8,12,16,20', minute=0)` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 60 * 2}` |
| `run-job--export_hermes_radar_snapshot` | `workflows.hud.tasks.hermes_radar_export.export_hermes_radar_snapshot` | `crontab(minute=0)` | `{'queue': WorkflowQueue.HOST, 'expires': 60 * 10}` |
| `run-job--refresh_hermes_radar` | `workflows.hud.tasks.hud_radar.refresh_hermes_radar` | `crontab(minute=5)` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 10}` |
| `run-job--get_schedules` | `workflows.hud.tasks.hud_logs.get_schedules` | `crontab(hour='0,4,8,12,16,20', minute=0)` | `{'queue': WorkflowQueue.HOST, 'os': ['any'], 'expires': 60 * 60}` |

## Output path

Existing tasks retain their app fetches, text formatting, `@feed` dump and Elasticsearch execution log. `@init_meter` now returns portable text and links by default. `@capture_hud_projection` publishes redacted output to `harqis-second-brain-hud`. The web HUD reads these snapshots without invoking a collector from a browser request. The old radar fallback remains callable for compatibility, but is no longer scheduled.

The 18 registered source adapters are all available in Add widget. The Second Brain Rainmeter projection is a legacy delivery client, not a recursive web widget. Ancillary screenshot capture, binding summaries, Hermes radar export and fallback jobs are listed above but are not standalone display widgets.

Windows foreground-window, mouse/iCUE, AutoHotkey and screenshot sources retain host affinity. API-backed Calendar, finance, forex, Jira, cost, job-summary and radar collectors run on `host`; schedule options and manual task routes agree. TCG orders and sell-cart retain their existing Windows placement because they export files and modify carts. Of 20 scheduled jobs, 12 use `host`, seven `hud`, and one `peon`. Legacy profile/agent launch commands are represented as captured context only; the browser does not execute desktop commands.
