"""Celery schedules durable PR discovery; the owner API retains connector secrets."""
import os
import time
import uuid

import httpx
from core.apps.sprout.app.celery import SPROUT
from workflows.hfl.tasks.timeline_suggestions import log_result_or_raise


@SPROUT.task(bind=True, max_retries=3)
@log_result_or_raise
def sync_github_pull_requests(self, *, batches=10, run_id=''):
    """Discover/backfill published PRs and reconcile ordinary linked review actions.

    Uses HFL_PERSONA_API_URL (owner frontend) or HFL_CORPUS_API_URL and the
    existing HFL_CORPUS_API_TOKEN. The owner must have an enabled GitHub connector
    and one peon Space. Progress is retained at the owner API across task retries.
    """
    if type(batches) is not int or not 1 <= batches <= 20:
        raise ValueError('batches must be between 1 and 20')
    identity = run_id or str(uuid.uuid4())
    base = (os.environ.get('HFL_PERSONA_API_URL') or os.environ.get('HFL_CORPUS_API_URL', '')).rstrip('/')
    if not base:
        from workflows.hfl.persistence import is_canonical_machine
        if is_canonical_machine():
            base = 'http://127.0.0.1:' + str(int(os.environ.get('HFL_API_PORT', '8082')))
    token = os.environ.get('HFL_CORPUS_API_TOKEN', '')
    started, applied, cycle_done = time.monotonic(), 0, False
    try:
        if not base or not token:
            raise ValueError('Owner API URL and token are required.')
        with httpx.Client(timeout=900, follow_redirects=False) as client:
            for _ in range(batches):
                response = client.post(base + '/api/hfl/github-updates/sync',
                    headers={'Authorization': 'Bearer ' + token},
                    json={'pages': 5, 'limit': 10, 'run_id': identity})
                response.raise_for_status()
                result = response.json()
                if result.get('status') == 'busy':
                    return {'status': 'busy', 'run_id': identity, 'applied': applied}
                applied += result['applied']
                cycle_done = cycle_done or result['discovery_complete']
                if result.get('errors'):
                    raise ValueError('PR synchronization has pending failures.')
                if (cycle_done and not result['pending']) or time.monotonic() - started >= 600:
                    break
        return {**result, 'run_id': identity, 'applied': applied,
                'discovery_complete': cycle_done, 'continuation_pending': not cycle_done or bool(result['pending'])}
    except Exception as exc:
        delay = 300
        if isinstance(exc, httpx.HTTPStatusError):
            raw = exc.response.headers.get('Retry-After', '')
            if raw.isdigit():
                delay = max(300, min(3600, int(raw)))
        raise self.retry(exc=RuntimeError('GitHub updates incomplete; durable progress retained.'),
                         countdown=delay, kwargs={'batches': batches, 'run_id': identity})
