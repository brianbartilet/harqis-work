"""Celery owns durable persona audits; the owning frontend owns profile data."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from core.apps.sprout.app.celery import SPROUT
from workflows.hfl.tasks.timeline_suggestions import log_result_or_raise


@SPROUT.task(bind=True, max_retries=2)
@log_result_or_raise
def persona_audit(self, run_id=''):
    """Run one idempotent audit via the owner API, including its private HFL receipt."""
    identity = run_id or 'weekly-' + datetime.now(ZoneInfo('Asia/Singapore')).strftime('%G-%V')
    base = (os.environ.get('HFL_PERSONA_API_URL') or os.environ.get('HFL_CORPUS_API_URL', '')).rstrip('/')
    token = os.environ.get('HFL_CORPUS_API_TOKEN', '')
    try:
        if not base or not token:
            raise ValueError('Configure the owner API URL and HFL API token.')
        response = httpx.post(base + '/api/hfl/roles/audit/run', json={'run_id': identity},
                              headers={'Authorization': 'Bearer ' + token}, timeout=900, follow_redirects=False)
        response.raise_for_status()
        value = response.json()
        if value.get('status') != 'complete' or value.get('report_pending'):
            raise ValueError('Persona audit or its HFL receipt needs retry.')
        return {'run_id': identity, 'status': value['status'], 'roles': len(value.get('roles', []))}
    except Exception:
        raise self.retry(exc=RuntimeError('Persona audit unavailable; retrying the same run.'), countdown=120)
