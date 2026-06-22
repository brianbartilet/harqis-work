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
WORKFLOW_PURCHASES = {

    'run-job--generate_tcg_mappings': {
        'task': 'workflows.purchases.tasks.tcg_mp_selling.generate_tcg_mappings',
        'schedule': crontab(hour='0', minute=0),
        'kwargs': {
            "cfg_id__tcg_mp": "TCG_MP",
            "cfg_id__echo_mtg": "ECHO_MTG",
            "cfg_id__echo_mtg_fe": "ECHO_MTG_FE",
            "cfg_id__scryfall": "SCRYFALL",
            "limit": 100
        },
        "options": {
            "queue": WorkflowQueue.TCG,
            "expires": 60 * 60 * 8
        },
        'manifesto': {
            'code_role': 'organize',
            'para_bucket': 'area',
            'express_target': 'file:tcg_mappings',
            'review_artifact': 'es_log+file',
            'hfl_signal': False,
        },
    },

    'run-job--generate_tcg_listings': {
        'task': 'workflows.purchases.tasks.tcg_mp_selling.generate_tcg_listings',
        'schedule': crontab(hour='1', minute=0),
        'kwargs': {
            "cfg_id__tcg_mp": "TCG_MP",
            "cfg_id__echo_mtg": "ECHO_MTG",
            "cfg_id__echo_mtg_fe": "ECHO_MTG_FE",
            "language": "EN",   # default; per-card EchoMTG language wins when present
            #"limit": 100
        },
        "options": {
            "queue": WorkflowQueue.TCG,
            "expires": 60 * 60 * 8
        },
        'manifesto': {
            'code_role': 'express',
            'para_bucket': 'area',
            'express_target': 'api:tcg_mp',
            'review_artifact': 'es_log+file',
            'hfl_signal': False,
        },
    },
    # ENABLED — price refresh, Mon+Thu 04:00, AFTER the daily mappings (00:00) and
    # listings (01:00), and AFTER radar_sold_inventory (same days, 02:00) so the
    # radar has reconciled sold inventory before quantities are recomputed. It SETS
    # each listing's quantity to the EchoMTG matching-copy count (it does not read the
    # live listing qty) and resets vanished listings to 0 for recreation — so radar
    # MUST run first: a copy sold-but-not-yet-removed from EchoMTG would otherwise
    # re-inflate the listing back to the stale count (over-listing sold cards; see
    # README "Known issues" #1/#2). NOTE: the 2h gap is wall-clock, not a hard
    # dependency — if radar overruns, update can start early; a Celery chain
    # (radar | update) would make the ordering guaranteed.
    'run-job--update_tcg_listings_prices': {
        'task': 'workflows.purchases.tasks.tcg_mp_selling.update_tcg_listings_prices',
        'schedule': crontab(day_of_week="mon,thu", hour='4', minute=0),
        'kwargs': {
            "cfg_id__tcg_mp": "TCG_MP",
            "cfg_id__echo_mtg": "ECHO_MTG",
            "cfg_id__echo_mtg_fe": "ECHO_MTG_FE"
        },
        "options": {
            "queue": WorkflowQueue.TCG,
            "expires": 60 * 60 * 24
        },
        'manifesto': {
            'code_role': 'express',
            'para_bucket': 'area',
            'express_target': 'api:tcg_mp',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },
    'run-job--download_scryfall_bulk_data': {
        'task': 'workflows.purchases.tasks.tcg_mp_selling.download_scryfall_bulk_data',
        # Run late on the 1st (22:00), NOT 00:00 — at midnight it collided with the
        # daily generate_tcg_mappings (00:00), which reads the newest all-cards file
        # while this writes it (partial-read risk). 22:00 leaves a clean file ready
        # for the 2nd onward; mappings on the 1st just uses the prior month's bulk.
        'schedule': crontab(
            day_of_month='1',
            hour=22,
            minute=0
        ),
        'kwargs': {
            "cfg_id__scryfall": "SCRYFALL"
        },
        "options": {
            "queue": WorkflowQueue.TCG,
            "expires": 60 * 60 * 24
        },
        'manifesto': {
            'code_role': 'capture',
            'para_bucket': 'area',
            'express_target': 'file:scryfall_bulk',
            'review_artifact': 'es_log+file',
            'hfl_signal': False,
        },
    },

    'run-job--generate_audit_for_tcg_orders': {
        'task': 'workflows.purchases.tasks.tcg_mp_selling.generate_audit_for_tcg_orders',
        'schedule': crontab(minute=0, hour="*/4"),
        'kwargs': {
            "cfg_id__tcg_mp": "TCG_MP"
        },
        "options": {
            "queue": WorkflowQueue.TCG,
            "expires": 60 * 60 * 4
        },
        'manifesto': {
            'code_role': 'distill',
            'para_bucket': 'area',
            'express_target': 'es_log',
            'review_artifact': 'es_log',
            'hfl_signal': False,
        },
    },

    # ENABLED — sold-inventory radar, Mon+Thu 02:00 — aligned to (and one step ahead
    # of) update_tcg_listings_prices (same days, 04:00) so EchoMTG inventory is
    # reconciled BEFORE update pushes EchoMTG copy counts onto listing quantities.
    # Runs after the daily mappings (00:00) / listings (01:00). Was monthly (1st
    # 03:00), which only preceded update when the 1st fell on a Mon/Thu — most update
    # runs then fired against un-reconciled inventory (the over-listing bug).
    # DESTRUCTIVE but SAFE-BY-TIER: dry_run=False so it acts, but min_confidence='high'
    # means it only auto-marks-sold/removes/reconciles the strongest signal —
    # listing_gone + a corroborating sold order (the mapped listing vanished AND the
    # product sold). Everything else (medium "still listed" matches, low orphans) is
    # written to the CSV (results/) + ES for manual approve-and-apply via
    # /radar-sold-inventory, not auto-actioned. It ALWAYS writes the review CSV.
    # NOTE: this is unattended destructive cleanup of the high-tier; flip dry_run=True
    # to make the scheduled run report-only.
    'run-job--radar_sold_inventory': {
        'task': 'workflows.purchases.tasks.sold_inventory_radar.radar_sold_inventory',
        'schedule': crontab(day_of_week="mon,thu", hour='2', minute=0),
        'kwargs': {
            'cfg_id__tcg_mp': 'TCG_MP',
            'cfg_id__echo_mtg': 'ECHO_MTG',
            'cfg_id__echo_mtg_fe': 'ECHO_MTG_FE',
            'dry_run': False,
            'min_confidence': 'high',     # auto-act on high-confidence only
            'orphan_mode': 'corroborated',
            'last_x_days': 60,
            'source': 'hybrid',
        },
        'options': {
            'queue': WorkflowQueue.TCG,
            'expires': 60 * 60 * 8,
        },
        'manifesto': {
            'code_role': 'distill',
            'para_bucket': 'area',
            'express_target': 'es_log+file',
            'review_artifact': 'es_log+file',
            'hfl_signal': False,
        },
    },





}

