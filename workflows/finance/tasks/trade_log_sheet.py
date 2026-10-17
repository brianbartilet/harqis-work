"""
workflows/finance/tasks/trade_log_sheet.py

Publishes trades from the local IBKR ledger to the trade log Google Sheet
(apps/google_apps). Google only — capturing from IBKR is the separate task in
tasks/ibkr_trades.py. Logic: workflows/finance/sheets_sync.py.
"""

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from workflows.finance.sheets_sync import sync_to_sheet


@SPROUT.task()
@log_result()
def sync_trade_log_sheet(**kwargs):
    """Append ledger trades that are missing from the trade log sheet (idempotent).

    Args:
        cfg_id__sheets: Config key for the trade log sheet (default 'GOOGLE_SHEETS_TRADE_LOG').

    Returns:
        dict with ledger / new counts and a one-line summary per appended row.
    """
    cfg_id__sheets = kwargs.get('cfg_id__sheets', 'GOOGLE_SHEETS_TRADE_LOG')
    return sync_to_sheet(cfg_id__sheets)
