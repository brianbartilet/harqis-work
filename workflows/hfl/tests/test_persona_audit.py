"""Worker ownership, idempotency, and bounded retries."""
from types import SimpleNamespace

import pytest


@pytest.mark.skip(reason='Manual integration: creates a real private persona-audit HFL entry and may append journal observations.')
def test__persona_audit():
    from workflows.hfl.tasks.persona_audit import persona_audit
    persona_audit.run(run_id='manual-integration-persona-audit')


def test__worker_calls_owning_frontend_with_same_run(monkeypatch):
    from workflows.hfl.tasks import persona_audit as module
    calls = []
    monkeypatch.setenv('HFL_PERSONA_API_URL', 'http://owner.test')
    monkeypatch.setenv('HFL_CORPUS_API_TOKEN', 'test-token')
    monkeypatch.setattr(module.httpx, 'post', lambda url, **kw: calls.append((url, kw)) or SimpleNamespace(
        raise_for_status=lambda:None, json=lambda:{'status':'complete','roles':[]}))
    result = module.persona_audit.run.__wrapped__(SimpleNamespace(), run_id='run-123')
    assert result['run_id'] == 'run-123'
    assert calls[0][0] == 'http://owner.test/api/hfl/roles/audit/run'
    assert calls[0][1]['json'] == {'run_id':'run-123'}
    assert calls[0][1]['follow_redirects'] is False


def test__worker_retries_failed_receipt_without_new_identity(monkeypatch):
    from workflows.hfl.tasks import persona_audit as module
    monkeypatch.setenv('HFL_PERSONA_API_URL', 'http://owner.test')
    monkeypatch.setenv('HFL_CORPUS_API_TOKEN', 'test-token')
    monkeypatch.setattr(module.httpx, 'post', lambda *args, **kw: SimpleNamespace(
        raise_for_status=lambda:None, json=lambda:{'status':'complete','report_pending':True}))
    with pytest.raises(RuntimeError, match='retrying the same run'):
        module.persona_audit.run.__wrapped__(SimpleNamespace(retry=lambda **kw:kw['exc']), run_id='run-123')
