"""Beat owns Action discovery; the frontend owns provider credentials and receipts."""
import os
import httpx

from core.apps.sprout.app.celery import SPROUT
from workflows.hfl.tasks.timeline_suggestions import log_result_or_raise


@SPROUT.task(bind=True, max_retries=2)
@log_result_or_raise
def reconcile_action_executions(self):
    base = os.environ.get('HFL_AGENT_BRIDGE_URL', '').rstrip('/')
    token = os.environ.get('HFL_AGENT_BRIDGE_TOKEN', '')
    if not base or not token:
        raise ValueError('Configure the existing HFL agent bridge URL and token.')
    try:
        with httpx.Client(timeout=240, follow_redirects=False) as client:
            response = client.post(base + '/api/hfl-agent/actions/reconcile',
                                   headers={'Authorization': 'Bearer ' + token})
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError:
        raise self.retry(exc=RuntimeError('Action reconciliation unavailable; persisted receipts retained.'), countdown=30)
