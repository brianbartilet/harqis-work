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

from datetime import timedelta
from celery.schedules import crontab
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
WORKFLOWS_DESKTOP = {

    'run-job--git_pull_on_paths': {
        'task': 'workflows.desktop.tasks.commands.git_pull_on_paths',
        'schedule':  crontab(minute='*/10'),
        'args': [],
        "options": {
            "expires": 60 * 60,
            "queue": WorkflowQueue.DEFAULT
        },
    },

    'run-job--git_pull_on_paths_broadcast': {
        'task': 'workflows.desktop.tasks.commands.git_pull_on_paths',
        'schedule': crontab(hour='*/4'),
        'args': [],
        "options": {
            "expires": 60 * 60 * 4,
            "queue": WorkflowQueue.DEFAULT_BROADCAST
        },
    },

    'run-job--set_desktop_hud_to_back': {
        'task': 'workflows.desktop.tasks.commands.set_desktop_hud_to_back',
        'schedule': crontab(minute='*/30'),
        'args': [],
        "options": {
            "expires": 60 * 60,
            "queue": WorkflowQueue.HUD
        },
    },

    'run-job--copy_files_targeted': {
        'task': 'workflows.desktop.tasks.commands.copy_files_targeted',
        'schedule': crontab(minute='*/30'),
        'kwargs': {
            "cfg_id__desktop_jobs": "DESKTOP"
        },
        "options": {
            "expires": 60 * 60,
            "queue": WorkflowQueue.DEFAULT},
    },

    'run-job--run_n8n_sequence': {
        'task': 'workflows.desktop.tasks.commands.run_n8n_sequence',
        'schedule': crontab(hour='0', minute='0'),
        'args': [],
        "options": {
            "expires": 60 * 60 * 8,
            "queue": WorkflowQueue.HOST
        },
    },

    'run-job--run_capture_logging': {
        'task': 'workflows.desktop.tasks.capture.run_capture_logging',
        'schedule': crontab(minute='0,15,30,45'),
        'kwargs': {
            "cfg_id__desktop_utils": "DESKTOP"
        },
        "options": {
            "queue": WorkflowQueue.PEON,
            "expires": 60 * 60
        },
    },

    'run-job--generate_daily_desktop_summary': {
        'task': 'workflows.desktop.tasks.capture.generate_daily_desktop_summary',
        'schedule': crontab(hour=23, minute=55),
        'kwargs': {
            "hud_item_name": "DESKTOP LOGS",
            "logs_output_path": "C:/Users/brian/GIT/harqis-work/logs/daily",
            "model": "claude-haiku-4-5-20251001",
        },
        "options": {
            "queue": WorkflowQueue.PEON,
            "expires": 60 * 60 * 24,
        },
    },

    'run-job--generate_weekly_desktop_summary': {
        'task': 'workflows.desktop.tasks.capture.generate_weekly_desktop_summary',
        'schedule': crontab(day_of_week='sun', hour=23, minute=58),
        'kwargs': {
            "logs_daily_path": "C:/Users/brian/GIT/harqis-work/logs/daily",
            "logs_output_path": "C:/Users/brian/GIT/harqis-work/logs/weekly",
            "model": "claude-haiku-4-5-20251001",
        },
        "options": {
            "queue": WorkflowQueue.PEON,
            "expires": 60 * 60 * 24 * 7,
        },
    },

}




