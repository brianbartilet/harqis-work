# Add import statements for tasks modules to make them accessible
import sys

# Register the Celery tasks only inside a Celery process (worker, Beat, or anything that
# imported the SPROUT app first). The trade log's logic modules (ibkr_ledger, sheets_sync)
# are Celery-free, so scripts/ibkr_trade_log.py can import them on hosts without the
# worker stack (see requirements-trade-log.txt) without loading every workflow's config.
if "celery" in sys.modules:
    import workflows.finance.tasks.ibkr_trades  # noqa: F401
    import workflows.finance.tasks.trade_log_sheet  # noqa: F401
