"""
workflows/finance/tasks/ibkr_trades.py

Captures new Interactive Brokers stock trades (Trade Confirmation Flex Query via
apps/ibkr) into the local IBKR ledger. IBKR only — publishing to Google Sheets is
the separate task in tasks/trade_log_sheet.py. Logic: workflows/finance/ibkr_ledger.py.
"""

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from workflows.finance.ibkr_ledger import capture_trades


@SPROUT.task()
@log_result()
def capture_ibkr_trades(**kwargs):
    """Append new IBKR stock trades to the local ledger (idempotent).

    Args:
        cfg_id__ibkr: Config key for IBKR (default 'IBKR').

    Returns:
        dict with fetched / new counts and a one-line summary per captured trade.
    """
    cfg_id__ibkr = kwargs.get('cfg_id__ibkr', 'IBKR')
    return capture_trades(cfg_id__ibkr)
