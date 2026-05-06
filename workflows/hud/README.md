# HUD Workflow

## Description

- Displays real-time data on a Windows desktop HUD via Rainmeter widgets.
- Aggregates data from Google Calendar, OANDA forex, TCG Marketplace, YNAB budgets, AppSheet (PC INVOICE table), and Elasticsearch logs.
- 15 scheduled Celery tasks push data to the desktop feed at various intervals.
- Tasks use the decorator chain: `@SPROUT.task` → `@log_result` → `@init_meter` → `@feed`.

## Queue

All tasks run on the `hud` queue (configured via `SPROUT.conf.task_routes`).

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `show_forex_account` | Every 15 min (weekdays) | OANDA forex account summary |
| `show_tcg_orders` | Every hour | TCG Marketplace open orders |
| `show_tcg_sell_cart` | Sundays at midnight | Match my listings to want-to-buy bids within `discount_threshold_pct` and queue them in the seller's sell cart for manual fulfilment. Multiprocess one worker per listing. |
| `show_jira_board` | Weekdays every hour | Pull In-Review / In-Progress / Ready / In-Analysis tickets from a Jira Software board (rapidView=`board_id`) and render them as a 4-section HUD widget. Queue: `peon`. |
| `get_desktop_logs` | Every 5 min | AI analysis of desktop activity logs |
| `take_screenshots_for_gpt_capture` | Every 10 min | Desktop screenshot capture |
| `show_calendar_information` | Every 15 min | Google Calendar events for today |
| `get_failed_jobs` | Every 15 min | Failed Celery task list |
| `show_mouse_bindings` | Every 60 sec | Mouse shortcut bindings display |
| `build_summary_mouse_bindings` | Daily at 1am | Summary of daily mouse bindings |
| `show_hud_profiles` | Daily at midnight | Active iCUE/Rainmeter HUD profiles |
| `show_ynab_budgets_info` | Every 4 hours | YNAB budget balances |
| `show_pc_daily_sales` | Every hour | PC DAILY SALES — sums `TOTAL PRICE` per `DATE` from the AppSheet `INVOICE` table for the last 60 days, grouped by month with a 24-dash separator. Same width as OANDA ACCOUNT; height shows 10 rows at a time, the rest scrolls. Queue: `hud`. |
| `show_ai_helper` | Daily at midnight | AI helper widget initialization |
| `get_schedules` | Every 4 hours | Upcoming calendar schedule |

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
| `tasks/sections.py` | HUD section layout helpers |

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

## DTOs / Constants

| Name | File | Description |
|------|------|-------------|
| `AppExe` | `constants.py` | Enum of Windows app executables (Docker, Chrome, PyCharm, etc.) |
| `Profile` | `constants.py` | Enum of iCUE/HUD profiles (BASE, BROWSER, MARKDOWN, CODING, etc.) |
| `APP_TO_PROFILE` | `constants.py` | Dict mapping `AppExe` to `Profile` |

## Prompt Templates

AI tasks use markdown prompts from `prompts/` (repo root):
- `desktop_analysis.md` — Prompt for log analysis (`get_desktop_logs`)

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
