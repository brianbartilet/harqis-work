import copy
import pytest
from fastapi import HTTPException
from modules.agents import entities, service, oversight, briefings
from modules.integrations import codex, store


@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path/'connectors.sqlite3'))
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    payload = {
        'thread/list': {'data': [{'id': 'thread-1', 'name': 'Implement feature', 'status': {'type': 'notLoaded'}}], 'nextCursor': None},
        'thread/turns/list': {'data': [{'id': 'turn-1', 'status': 'completed', 'completedAt': 1790000000,
            'items': [{'type': 'userMessage', 'content': 'PRIVATE PROMPT'},
                      {'type': 'commandExecution', 'output': 'PRIVATE OUTPUT'},
                      {'type': 'agentMessage', 'phase': 'final_answer', 'text': 'Tests passed. https://example.org/report token=private'}]}], 'nextCursor': None},
        'plugin/list': {'marketplaces': [{'name': 'local', 'plugins': [
            {'id': 'git', 'name': 'GitHub', 'installed': True, 'enabled': True},
            {'id': 'unused', 'name': 'Uninstalled', 'installed': False}]}]}}
    calls = []
    class RPC:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, method, params):
            calls.append((method, params))
            result = payload[method]
            if isinstance(result, Exception): raise result
            return copy.deepcopy(result)
    monkeypatch.setattr(codex, 'CodexRPC', RPC)
    store.save('alice', 'codex', {'site': codex.installation(), 'account': 'Codex host',
        'account_id': codex.installation(), 'status': 'Connected', 'enabled': True}, codex.credentials({}))
    return payload, calls


def test_mapping_receipts_isolation_and_customization(host):
    agent = codex.link('alice', {})['item']
    codex.refresh('alice', agent['id'])
    inventory = entities.snapshot('alice')
    assert sorted(i['kind'] for i in inventory['items']) == ['application', 'connector', 'task']
    assert entities.snapshot('bob')['items'] == []
    with pytest.raises(HTTPException): codex.refresh('bob', agent['id'])
    receipts = [e for e in service.store().events() if e['payload']['kind'] == 'codex-turn']
    assert len(receipts) == 1
    assert receipts[0]['payload']['evidence'] == ['https://example.org/report']
    assert 'PRIVATE' not in str(receipts)
    assert 'token=private' not in str(receipts)
    assert 'token=[redacted]' in str(receipts)
    assert briefings.agent_updates('alice')[0]['state'] == 'completed'
    assert briefings.agent_updates('bob') == []
    service.store().save({**agent, 'name': 'Ada'}, identity=agent['id'], version=agent['version'])
    assert codex.link('alice', {})['item']['name'] == 'Ada'
    assert all(method in {'thread/list', 'thread/turns/list', 'plugin/list'} for method, _ in host[1])


def test_partial_empty_removed_and_merge_refresh(host):
    agent = codex.link('alice', {})['item']
    app = next(i for i in entities.snapshot('alice')['items'] if i['kind'] == 'application')
    other = entities.entity('application', 'another', 'git', 'GitHub')
    entities.observe('alice', [other], [])
    merge = entities.merge('alice', app['id'], other['id'], True)
    codex.refresh('alice', agent['id'])
    assert app['id'] not in {i['id'] for i in entities.snapshot('alice')['items']}
    entities.unmerge('alice', merge['merge_id'])
    payload, _ = host
    payload['plugin/list'] = HTTPException(422, 'unsupported')
    assert codex.refresh('alice', agent['id'])['warnings']
    assert next(i for i in entities.snapshot('alice')['items'] if i['id'] == app['id'])['state'] == 'unsupported'
    payload['plugin/list'] = {'marketplaces': []}
    codex.refresh('alice', agent['id'])
    assert next(i for i in entities.snapshot('alice')['items'] if i['id'] == app['id'])['state'] == 'no longer observed'
    payload['thread/list'] = HTTPException(503, 'offline')
    assert codex.refresh('alice', agent['id'])['warnings']
    assert any(i['state'] == 'stale' for i in entities.snapshot('alice')['items'])


def test_manual_profile_reuse_and_no_duplicate_producer(host):
    manual = service.initialize().save({**service.defaults('My Codex'), 'runtime': 'codex'})
    linked = codex.link('alice', {'agent_id': manual['id']})['item']
    assert linked['id'] == manual['id']
    assert codex.link('alice', {})['item']['id'] == manual['id']
    second = service.store().save({**service.defaults('Other'), 'runtime': 'codex'})
    with pytest.raises(HTTPException): codex.link('alice', {'agent_id': second['id']})


def test_pagination_refreshes_recent_work_and_preserves_tasks(host):
    payload, calls = host
    agent = codex.link('alice', {})['item']
    payload['thread/list']['nextCursor'] = 'next'
    codex.refresh('alice', agent['id'])
    calls.clear()
    codex.refresh('alice', agent['id'])
    assert any(p.get('cursor') == 'next' for m, p in calls if m == 'thread/list')
    assert any('cursor' not in p and p.get('archived') is False for m, p in calls if m == 'thread/list')
    payload['thread/list'] = {'data': [], 'nextCursor': None}
    codex.refresh('alice', agent['id'])
    assert any(i['kind'] == 'task' and i['state'] != 'no longer observed' for i in entities.snapshot('alice')['items'])


def test_unnamed_threads_do_not_copy_prompt_previews(host):
    payload, _ = host
    task = payload['thread/list']['data'][0]
    task.pop('name')
    task['preview'] = 'PRIVATE ORIGINAL PROMPT'
    codex.link('alice', {})
    assert 'PRIVATE ORIGINAL PROMPT' not in str(entities.snapshot('alice'))


def test_oversight_is_owner_scoped_and_no_dispatch(host, monkeypatch):
    codex.link('alice', {})
    from modules.agents import audit
    monkeypatch.setattr(audit, 'deliver_pending', lambda: {'delivered': 0, 'pending': 1})
    result = oversight.reconcile('alice')
    assert result['status'] == 'complete'
    assert oversight.snapshot('alice')[0]['reporting'] == 'supported'
    assert oversight.snapshot('bob') == []
    assert len([e for e in service.store().events() if e['payload']['kind'] == 'codex-turn']) == 1


def test_transport_rejects_execution_methods():
    from modules.integrations.codex_transport import CodexRPC
    with pytest.raises(ValueError): CodexRPC().request('turn/start', {})


def test_connector_routes_and_worker_auth(host, authenticated_client, monkeypatch):
    from test_hfl_agent_bridge import owner_headers
    client = authenticated_client
    assert client.post('/integrations/api/connectors/codex/save', json={}).status_code == 403
    headers = owner_headers()
    assert client.post('/integrations/api/connectors/codex/test', json={}, headers=headers).status_code == 200
    assert not store.get('frontend-test-user', 'codex').get('enabled')
    assert client.post('/integrations/api/connectors/codex/save', json={}, headers=headers).status_code == 200
    enabled = client.post('/integrations/api/connectors/codex/toggle', json={'enabled': True}, headers=headers)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()['discovery']['counts']['applications'] == 1
    cards = client.get('/integrations/api/connectors').json()['items']
    from modules.integrations.service import PROVIDERS
    assert all(isinstance(card['capabilities'], list) for card in cards)
    assert next(card for card in cards if card['provider'] == 'codex')['capabilities'] == PROVIDERS['codex']['capabilities']
    fleet_page = client.get('/agents').text
    assert 'img/connectors/codex.svg' in fleet_page
    assert client.post('/api/hfl/fleet/reconcile').status_code == 401
    from modules.agents import oversight_api
    monkeypatch.setattr(oversight_api, 'reconcile', lambda user: {'owner': user})
    response = client.post('/api/hfl/fleet/reconcile', headers={'Authorization': 'Bearer frontend-test-hfl-api-token'})
    assert response.status_code == 200 and response.json()['owner'] == 'frontend-test-user'


def test_receipt_outbox_retry_is_deduplicated(host, monkeypatch):
    codex.link('alice', {})
    from modules.agents import audit
    from workflows.hfl import persistence
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '0')
    event = next(e for e in service.store().events() if e['payload']['kind'] == 'codex-turn')
    calls = []
    def submit(entry, **kwargs):
        calls.append(kwargs['dedup_key'])
        assert 'PRIVATE' not in entry.what_happened
        return {'delivery': 'outbox'}
    monkeypatch.setattr(persistence, 'submit_hfl_entry', submit)
    assert audit.deliver_pending([event['id']])['delivered'] == 1
    assert audit.deliver_pending([event['id']])['delivered'] == 0
    assert calls == ['fleet:' + event['id']]


def test_worker_schedule_and_bounded_retry(monkeypatch):
    from workflows.hfl.tasks.fleet_observations import reconcile_fleet_observations
    from workflows.hfl.tasks_config import WORKFLOW_HFL
    item = WORKFLOW_HFL['run-job--reconcile_fleet_observations']
    assert item['options']['expires'] == 300
    assert item['schedule']._orig_minute == '*/5'
    monkeypatch.setenv('HFL_PERSONA_API_URL', 'https://owner.example.test')
    monkeypatch.setenv('HFL_CORPUS_API_TOKEN', 'test-token')
    import httpx
    def request(self, url, **kwargs):
        assert url == 'https://owner.example.test/api/hfl/fleet/reconcile'
        return httpx.Response(200, json={'status': 'complete', 'warnings': []}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.Client, 'post', request)
    # Exercise the task body without the external Elasticsearch logging decorator.
    assert reconcile_fleet_observations.run.__wrapped__(reconcile_fleet_observations)['status'] == 'complete'
