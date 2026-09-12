"""Daily previous-day suggestion cache and explicit historical exploration."""
from datetime import datetime, timedelta

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from workflows.hfl.timeline import SGT, explore_period, write_completion
from workflows.hfl.timeline_store import FollowUpStore, store_path


@SPROUT.task()
@log_result()
def generate_timeline_suggestions(start="", end="", run_id=""):
    previous=(datetime.now(SGT).date()-timedelta(days=1)).isoformat()
    canonical=FollowUpStore(store_path())
    for receipt in canonical.receipts(pending_only=True)[:50]:
        write_completion(receipt["followup_id"],receipt["version"],store=canonical)
    return explore_period(start or previous,end or start or previous,run_id=run_id or None,store=canonical)
