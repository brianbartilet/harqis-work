"""Beat-owned reconciliation; connector credentials and Codex stay on the owner host."""
import os
import httpx
from core.apps.sprout.app.celery import SPROUT
from workflows.hfl.tasks.timeline_suggestions import log_result_or_raise


@SPROUT.task(bind=True, max_retries=2)
@log_result_or_raise
def reconcile_fleet_observations(self):
    base = (os.environ.get('HFL_PERSONA_API_URL') or os.environ.get('HFL_CORPUS_API_URL', '')).rstrip('/')
    if not base:
        from workflows.hfl.persistence import is_canonical_machine
        if is_canonical_machine():
            base = 'http://127.0.0.1:' + str(int(os.environ.get('HFL_API_PORT', '8082')))
    token = os.environ.get('HFL_CORPUS_API_TOKEN', '')
    try:
        if not base or not token:
            raise ValueError('Owner API URL and token are required.')
        with httpx.Client(timeout=240, follow_redirects=False) as client:
            response = client.post(base + '/api/hfl/fleet/reconcile', headers={'Authorization': 'Bearer ' + token})
            response.raise_for_status()
            result = response.json()
        if result.get('warnings'):
            raise ValueError('Some observations remain unavailable.')
        return result
    except Exception:
        raise self.retry(exc=RuntimeError('Fleet observation incomplete; durable observations retained.'), countdown=300)
