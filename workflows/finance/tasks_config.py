"""
Beat schedule for the finance workflow.

Not yet merged into workflows/config.py — see workflows/finance/README.md
("Activating in workflows/config.py"). Entries below are parked as # comments so
they can be enabled deliberately on a host that runs the Celery stack.

  - capture_ibkr_trades / sync_trade_log_sheet: until then, scheduled by Windows
    Task Scheduler via scripts/ibkr_trade_log.py (same logic, no Celery needed).
    Enable only one schedule owner at a time.
"""
from celery.schedules import crontab

from workflows.queues import WorkflowQueue

WORKFLOW_FINANCE = {

    # ── capture_ibkr_trades ──────────────────────────────────────────────────
    # Inferred schedule: every 30 minutes — trade confirmations appear shortly after
    # a fill, the task is idempotent, and 48 runs/day stays far below IBKR's Flex
    # pacing limit (10 requests/minute per token). IBKR only; writes the local ledger.
    # Required kwargs: cfg_id__ibkr='IBKR'
    # Activate by uncommenting and importing in workflows/config.py
    #
    # 'run-job--capture_ibkr_trades': {
    #     'task': 'workflows.finance.tasks.ibkr_trades.capture_ibkr_trades',
    #     'schedule': crontab(minute='*/30'),
    #     'kwargs': {
    #         'cfg_id__ibkr': 'IBKR',
    #     },
    #     'options': {
    #         'queue': WorkflowQueue.DEFAULT,
    #         'expires': 60 * 25,
    #     },
    #     'manifesto': {
    #         'code_role': 'capture',
    #         'para_bucket': 'area',
    #         'express_target': 'file:ibkr_trade_ledger',
    #         'review_artifact': 'es_log+file',
    #         'hfl_signal': False,
    #     },
    # },

    # ── sync_trade_log_sheet ─────────────────────────────────────────────────
    # Inferred schedule: every 30 minutes, 5 minutes after the capture, so new
    # ledger entries reach the sheet within ~35 minutes. Google only; reads the ledger.
    # Required kwargs: cfg_id__sheets='GOOGLE_SHEETS_TRADE_LOG'
    #
    # 'run-job--sync_trade_log_sheet': {
    #     'task': 'workflows.finance.tasks.trade_log_sheet.sync_trade_log_sheet',
    #     'schedule': crontab(minute='5,35'),
    #     'kwargs': {
    #         'cfg_id__sheets': 'GOOGLE_SHEETS_TRADE_LOG',
    #     },
    #     'options': {
    #         'queue': WorkflowQueue.DEFAULT,
    #         'expires': 60 * 25,
    #     },
    #     'manifesto': {
    #         'code_role': 'express',
    #         'para_bucket': 'area',
    #         'express_target': 'api:google_sheets',
    #         'review_artifact': 'es_log+api:google_sheets',
    #         'hfl_signal': False,
    #     },
    # },

}
