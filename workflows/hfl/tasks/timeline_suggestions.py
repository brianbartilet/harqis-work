"""Daily previous-day suggestion cache and explicit historical exploration."""
from datetime import datetime, timedelta
from functools import wraps

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from workflows.hfl.timeline import SGT, explore_period, write_completion
from workflows.hfl.timeline_store import FollowUpStore, store_path


def log_result_or_raise(function):
    """Keep core logging counters without hiding failures from Celery."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        failure = None

        @log_result()
        @wraps(function)
        def recorded(*args, **kwargs):
            nonlocal failure
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                failure = exc
                raise

        result = recorded(*args, **kwargs)
        if failure is not None:
            raise failure
        return result
    return wrapped


@SPROUT.task()
@log_result_or_raise
def generate_timeline_suggestions(start="", end="", run_id=""):
    previous=(datetime.now(SGT).date()-timedelta(days=1)).isoformat()
    canonical=FollowUpStore(store_path())
    for receipt in canonical.receipts(pending_only=True)[:50]:
        write_completion(receipt["followup_id"],receipt["version"],store=canonical)
    return explore_period(start or previous,end or start or previous,run_id=run_id or None,store=canonical)
