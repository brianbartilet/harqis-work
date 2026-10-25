"""Scheduler boundary for the owner-connected GitHub PR importer."""
import pytest
from workflows.hfl.tasks.github_updates import sync_github_pull_requests


@pytest.mark.skip(reason='Live task creates canonical HFL entries/actions and updates peon workspace and GitHub links.')
def test__sync_github_pull_requests():
    sync_github_pull_requests(batches=1)


def test__sync_github_pull_requests_rejects_unbounded_work():
    with pytest.raises(ValueError, match='batches'):
        sync_github_pull_requests.run.__wrapped__(None, batches=21)


def test__sync_github_pull_requests_drains_resumable_batches(monkeypatch):
    import httpx
    from workflows.hfl.tasks import github_updates as task
    monkeypatch.setenv('HFL_CORPUS_API_URL', 'https://owner.example.test')
    monkeypatch.delenv('HFL_PERSONA_API_URL', raising=False)
    monkeypatch.setenv('HFL_CORPUS_API_TOKEN', 'test-token')
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            calls.append(kwargs)
            return httpx.Response(200, json={'status': 'complete', 'applied': 1, 'pending': 0,
                'errors': [], 'discovery_complete': len(calls) == 2}, request=httpx.Request('POST', url))
    monkeypatch.setattr(task.httpx, 'Client', Client)
    result = sync_github_pull_requests.run.__wrapped__(None, batches=3, run_id='same-run')
    assert result['applied'] == 2 and not result['continuation_pending']
    assert len(calls) == 2 and all(c['json']['run_id'] == 'same-run' for c in calls)


def test__sync_github_pull_requests_respects_retry_after(monkeypatch):
    import httpx
    from workflows.hfl.tasks import github_updates as task
    monkeypatch.setenv('HFL_CORPUS_API_URL', 'https://owner.example.test')
    monkeypatch.delenv('HFL_PERSONA_API_URL', raising=False)
    monkeypatch.setenv('HFL_CORPUS_API_TOKEN', 'test-token')
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            return httpx.Response(429, headers={'Retry-After': '600'}, request=httpx.Request('POST', url))
    class Task:
        def retry(self, **kwargs):
            assert kwargs['countdown'] == 600 and kwargs['kwargs']['run_id'] == 'same-run'
            return RuntimeError('retry verified')
    monkeypatch.setattr(task.httpx, 'Client', Client)
    with pytest.raises(RuntimeError, match='retry verified'):
        sync_github_pull_requests.run.__wrapped__(Task(), run_id='same-run')
