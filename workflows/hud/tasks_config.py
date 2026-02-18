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
            "queue": "hud",
            "expires": 60 * 5
        },
    },

    'run-job--show_tcg_orders': {
        'task': 'workflows.hud.tasks.hud_tcg.show_tcg_orders',
        'schedule': crontab(minute='*/30'),
        'kwargs': {
            "cfg_id__tcg_mp": "TCG_MP",
            "cfg_id__scryfall": "SCRYFALL",
            "cfg_id__calendar": "GOOGLE_APPS"
        },
        "options": {
            "queue": "tcg",
            "expires": 60 * 30
        },
    },

    'run-job--get_desktop_logs': {
        'task': 'workflows.hud.tasks.hud_gpt.get_desktop_logs',
        'schedule': crontab(minute='5'),
        'kwargs': {
            "cfg_id__desktop": "DESKTOP",
            "cfg_id__calendar": "GOOGLE_APPS"
        },
        "options": {
            "queue": "default",
            "expires": 60 * 5
        },
    },

    'run-job--take_screenshots_for_gpt_capture': {
        'task': 'workflows.hud.tasks.hud_gpt.take_screenshots_for_gpt_capture',
        'schedule': crontab(minute='10,20,30,40,50,00'),
        'kwargs': {
            "cfg_id__desktop": "DESKTOP"
        },
        "options": {
            "queue": "default",
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
            "queue": "hud",
            "expires": 60 * 30
        },
    },

    'run-job--get_failed_jobs': {
        'task': 'workflows.hud.tasks.hud_logs.get_failed_jobs',
        'schedule': crontab(minute='*/15'),
        "options": {
            "queue": "hud",
            "expires": 60 * 15
        },
    },

    'run-job--show_mouse_bindings': {
        'task': 'workflows.hud.tasks.hud_utils.show_mouse_bindings',
        'schedule': timedelta(seconds=15),
        'kwargs': {
            "cfg_id__calendar": "GOOGLE_APPS"
        },
        "options": {
            "queue": "hud",
            "expires": 60 * 1
        },
    },

    'run-job--build_summary_mouse_bindings': {
        'task': 'workflows.hud.tasks.hud_utils.build_summary_mouse_bindings',
        'schedule': crontab(hour='1'),
        'kwargs': {
            "cfg_id__desktop": "DESKTOP"
        },
        "options": {
            "queue": "default",
            "expires": 60 * 60
        },
    },

    'run-job--show_hud_profiles': {
        'task': 'workflows.hud.tasks.hud_utils.show_hud_profiles',
        'schedule': crontab(hour='00'),
        "options": {
            "queue": "hud",
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
            "queue": "hud",
            "expires": 60 * 60
        }
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
            "queue": "hud",
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
            "queue": "hud",
            "expires": 60 * 60}
    },


}

