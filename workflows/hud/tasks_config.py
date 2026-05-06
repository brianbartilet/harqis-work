"""
This module is responsible for setting up and scheduling periodic tasks with Celery for executing web requests. It leverages Celery's ability to run tasks at specified intervals, automating the process of sending web requests as part of the application's workflow operations.

Scheduled tasks are defined in the `TASKS_SEND_WEB_REQUESTS` dictionary. Each entry in this dictionary specifies a unique task that is scheduled to run periodically. The configuration of these tasks includes the task function to be executed, the schedule of execution, and any arguments required by the task function.

Scheduled Task Configuration:
- `task`: A string that specifies the import path to the task function. This function is called each time the task is executed.
- `schedule`: A `datetime.timedelta` object that defines how often the task is executed. For example, a schedule of `timedelta(seconds=10)` means the task will run every 10 seconds.
- `args`: A list of arguments that will be passed to the task function upon execution. This list should match the expected arguments of the function.

Example:
The task 'run-test-sample-workflow-web-request' is configured to periodically execute the `send_requests` function found in the module `core.demo.workflows.__tpl_workflow_builder.workflows.send_web_requests`. It runs every 10 seconds without requiring any additional arguments (`'args': []`).

Usage:
- To use this module, ensure Celery is properly set up and configured in your project. Then, incorporate the `TASKS_SEND_WEB_REQUESTS` dictionary into your Celery Beat schedule configuration to start scheduling these tasks.
- Add to __init__.py imports to register tasks properly with Celery.
References:
- For an overview of setting up periodic tasks with Celery, see the Celery documentation on Periodic Tasks: https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html
- For solutions to common issues such as the Celery Beat UnpicklingError, consult: https://stackoverflow.com/questions/31468354/unpicklingerror-on-celerybeat-startup
"""

from celery.schedules import crontab
from datetime import timedelta
from workflows.queues import WorkflowQueue

"""
A dictionary mapping task identifiers to their configuration for scheduling.

This includes:
- 'task': The dotted path to the function to execute as a task.
- 'schedule': The frequency of execution, defined as a datetime.timedelta for recurring tasks.
- 'args': A list of arguments to pass to the task function.

Example task 'run-test-sample-workflow' is scheduled to run every 10 seconds, executing
the 'run_sample_workflow_add' function with specified arguments.
"""
WORKFLOWS_HUD = {

    'run-job--show_forex_account': {
        'task': 'workflows.hud.tasks.hud_forex.show_forex_account',
        'schedule': crontab(
            day_of_week="mon,tue,wed,thu,fri",
            minute='*/15'),
        'kwargs': {
            "cfg_id__oanda":"OANDA",
            "cfg_id__calendar": "GOOGLE_APPS",
            },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 5
        },
    },

    'run-job--show_tcg_orders': {
        'task': 'workflows.hud.tasks.hud_tcg.show_tcg_orders',
        'schedule': crontab(minute=0),
        'kwargs': {
            "cfg_id__tcg_mp": "TCG_MP",
            "cfg_id__scryfall": "SCRYFALL",
            "cfg_id__calendar": "GOOGLE_APPS"
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 30
        },
    },

    # ── show_tcg_sell_cart ───────────────────────────────────────────────────
    # Inferred schedule: weekly on Sunday at 00:00 — the matching pass talks to
    # the marketplace for every listing the user owns, so a once-per-week
    # cadence keeps load + noise low while still surfacing fresh bids.
    # `expires`: 60 * 60 * 24 — a missed Sunday run can still fire any time
    # within the same day; after that the result is stale.
    'run-job--show_tcg_sell_cart': {
        'task': 'workflows.hud.tasks.hud_tcg.show_tcg_sell_cart',
        'schedule': crontab(hour=0, minute=0),
        'kwargs': {
            "cfg_id__tcg_mp": "TCG_MP",
            "worker_count": 3
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60 * 8,
        },
    },

    # ── show_jira_board ──────────────────────────────────────────────────────
    # Inferred schedule: weekdays every hour on the hour. Pulls In-Review /
    # In-Progress / Ready / In-Analysis tickets from a Jira Software board so
    # the user can scan the team's queue without opening the browser.
    # `expires`: 60 * 30 — a missed run can still fire within the 30-minute
    # window; after that the next hourly tick will refresh anyway.
    'run-job--show_jira_board': {
        'task': 'workflows.hud.tasks.hud_jira.show_jira_board',
        'schedule': crontab(day_of_week='mon-fri', minute=0),
        'kwargs': {
            "cfg_id__jira": "JIRA",
            # Numeric ids only — full URLs are built by show_jira_board from
            # the configured Jira domain (apps_config.yaml::JIRA.app_data.domain
            # ← JIRA_DOMAIN env var).
            "board_id":      1790,    # /secure/RapidBoard.jspa?rapidView=
            "dashboard_id":  24135,   # /secure/Dashboard.jspa?selectPageId=
            "repository_id": 24135,   # /secure/Dashboard.jspa?selectPageId=
            "structure_id":  616,     # /secure/StructureBoard.jspa?s=
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 30,
        },
    },

    'run-job--get_desktop_logs': {
        'task': 'workflows.hud.tasks.hud_gpt.get_desktop_logs',
        'schedule': crontab(minute='5'),
        'kwargs': {
            "cfg_id__desktop": "DESKTOP",
            "cfg_id__calendar": "GOOGLE_APPS",
            "model": "claude-haiku-4-5-20251001",
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60
        },
    },

    'run-job--take_screenshots_for_gpt_capture': {
        'task': 'workflows.hud.tasks.hud_gpt.take_screenshots_for_gpt_capture',
        'schedule': crontab(minute='10,20,30,40,50,00'),
        'kwargs': {
            "cfg_id__desktop": "DESKTOP"
        },
        "options": {
            "queue": WorkflowQueue.DEFAULT,
            "expires": 60 * 10
        },
    },
    
    'run-job--show_calendar_information': {
        'task': 'workflows.hud.tasks.hud_calendar.show_calendar_information',
        'schedule': crontab(minute='15,30,45,00'),
        'kwargs': {
            "cfg_id__calendar": "GOOGLE_APPS",
            "cfg_id__elevenlabs": "ELEVEN_LABS"},
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 30
        },
    },

    'run-job--get_failed_jobs': {
        'task': 'workflows.hud.tasks.hud_logs.get_failed_jobs',
        'schedule': crontab(minute='*/15'),
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 15
        },
    },

    # Cadence bumped from 15s → 60s. Each invocation actually takes 14-22s
    # (cold-imports + win32 GetForegroundWindow + Rainmeter ini write under
    # gevent contention), so 15s scheduling kept a worker greenlet permanently
    # saturated and starved every other HUD task. 60s gives ~4× headroom and
    # the active-app readout doesn't need sub-minute precision.
    'run-job--show_mouse_bindings': {
        'task': 'workflows.hud.tasks.hud_utils.show_mouse_bindings',
        'schedule': timedelta(seconds=60),
        'kwargs': {
            "cfg_id__calendar": "GOOGLE_APPS"
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 2
        },
    },

    'run-job--build_summary_mouse_bindings': {
        'task': 'workflows.hud.tasks.hud_utils.build_summary_mouse_bindings',
        'schedule': crontab(hour='1'),
        'kwargs': {
            "cfg_id__desktop": "DESKTOP"
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60
        },
    },

    'run-job--show_hud_profiles': {
        'task': 'workflows.hud.tasks.hud_utils.show_hud_profiles',
        'schedule': crontab(hour='00'),
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60
        },
    },

    'run-job--show_ynab_budgets_info': {
        'task': 'workflows.hud.tasks.hud_finance.show_ynab_budgets_info',
        'schedule': crontab(hour='0,4,8,12,16,20'),
        'kwargs': {
            "cfg_id__ynab": "YNAB",
            "cfg_id__calendar": "GOOGLE_APPS"},
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60
        }
    },

    # ── show_pc_daily_sales ──────────────────────────────────────────────────
    # Hourly pull of gross daily sales (sum of TOTAL PRICE per DATE) from the
    # AppSheet INVOICE table. Renders 60 days grouped by month; only
    # `visible_lines` are visible at once — the rest scrolls.
    # `expires`: 60 * 60 — full-cadence per the brief; missed run still fires
    # within the hour, after that the next tick refreshes.
    'run-job--show_pc_daily_sales': {
        'task': 'workflows.hud.tasks.hud_finance.show_pc_daily_sales',
        'schedule': crontab(minute=0),
        'kwargs': {
            "cfg_id__appsheet": "APPSHEET",
            "days": 60,
            "visible_lines": 10,
            "amount_field": "TOTAL PRICE",
            "date_field": "DATE",
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60,
        },
    },

    'run-job--show_ai_helper': {
        'task': 'workflows.hud.tasks.hud_utils.show_ai_helper',
        'schedule': crontab(hour='0'),
        'kwargs': {
            "cfg_id__n8n": "N8N",
            "cfg_id__eleven": "ELEVEN_LABS",
            "cfg_id__py": "PYTHON_RUNNER"
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60
        }
    },

    'run-job--get_schedules': {
        'task': 'workflows.hud.tasks.hud_logs.get_schedules',
        'schedule': crontab(hour='0,4,8,12,16,20'),
        'kwargs': {
            "cfg_id__calendar": "GOOGLE_APPS",
        },
        "options": {
            "queue": WorkflowQueue.HUD,
            "expires": 60 * 60}
    },

}

