import json
import uuid
import httpx
import pytest
from fastapi import HTTPException
from modules.integrations import nod, nod_demo
from modules.agents import service


@pytest.fixture
def linked(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_NOD_MOCK', '1')
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path/'connectors.sqlite3'))
    return nod.link('alice', {})['item']


def message(agent, text='Hello'):
    view = nod.state('alice', agent['id'])
    return {'thread_id': view['thread_id'], 'binding': view['binding'], 'request_id': str(uuid.uuid4()), 'text': text}


def test_link_owner_and_deduplicated_message(linked):
    assert nod.link('alice', {})['item']['id'] == linked['id']
    with pytest.raises(HTTPException) as denied:
        nod.state('bob', linked['id'])
    assert denied.value.status_code == 404
    raw = message(linked)
    first = nod.send('alice', linked['id'], raw)
    assert nod.send('alice', linked['id'], raw) == first
    assert len(nod.state('alice', linked['id'])['turns']) == 1
    with pytest.raises(HTTPException) as conflict:
        nod.send('alice', linked['id'], {**raw, 'text': 'Different instruction'})
    assert conflict.value.status_code == 409


def test_stale_binding_thread_and_deactivated_agent(linked):
    raw = message(linked)
    for change in ({'binding': 'stale'}, {'thread_id': str(uuid.uuid4())}):
        with pytest.raises(HTTPException) as stale:
            nod.send('alice', linked['id'], {**raw, **change})
        assert stale.value.status_code == 409
    service.store().save({**linked, 'active': False}, identity=linked['id'], version=linked['version'])
    with pytest.raises(HTTPException):
        nod.send('alice', linked['id'], raw)


def test_timeout_after_acceptance_reconciles_without_second_post(linked, monkeypatch):
    original = nod_demo.MockNod.request
    posts = []
    def uncertain(self, method, path, **kwargs):
        result = original(self, method, path, **kwargs)
        if method == 'POST':
            posts.append(path)
            raise HTTPException(502, 'Response lost after Nod accepted the message')
        return result
    monkeypatch.setattr(nod_demo.MockNod, 'request', uncertain)
    raw = message(linked)
    with pytest.raises(HTTPException):
        nod.send('alice', linked['id'], raw)
    assert nod.send('alice', linked['id'], raw)['messageId'] == raw['request_id']
    assert posts == ['/api/messages']


def test_approval_and_stop_are_explicit(linked):
    nod.send('alice', linked['id'], message(linked, 'Show an approval'))
    view = nod.state('alice', linked['id'])
    approval = view['messages'][-1]
    raw = {**message(linked, 'Decline this action.'), 'approval_id': approval['approval']['id'], 'message_id': approval['id']}
    with pytest.raises(HTTPException):
        nod.send('alice', linked['id'], raw)
    first = nod.send('alice', linked['id'], {**raw, 'approved': False})
    assert nod.send('alice', linked['id'], {**raw, 'approved': False}) == first
    with pytest.raises(HTTPException):
        nod.send('alice', linked['id'], {**raw, 'approved': True, 'request_id': str(uuid.uuid4())})
    nod.send('alice', linked['id'], message(linked, 'Another approval'))
    with pytest.raises(HTTPException):
        nod.stop('alice', linked['id'], {'thread_id': view['thread_id'], 'binding': view['binding']})
    nod.stop('alice', linked['id'], {'confirmed': True, 'thread_id': view['thread_id'], 'binding': view['binding']})
    assert all(t['status'] != 'waiting' for t in nod.state('alice', linked['id'])['turns'])


def test_capture_excludes_conversation_and_never_delivers_mock(linked, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('Preview must not reach corpus')
    monkeypatch.setattr('workflows.hfl.persistence.submit_hfl_entry', forbidden)
    nod.send('alice', linked['id'], message(linked, 'PRIVATE MESSAGE'))
    nod.capture('alice', linked['id'])
    nod.capture('alice', linked['id'])
    events = [e for e in service.store().events(linked['id']) if e['payload']['kind'] == 'nod-turn']
    assert len(events) == 1 and events[0]['payload']['mock']
    assert 'PRIVATE MESSAGE' not in json.dumps(events)


def test_http_contract_and_redacted_errors(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers['authorization'] == 'Bearer SECRET'
        if request.url.path == '/api/health':
            return httpx.Response(200, json={'ok': True})
        if request.method == 'GET':
            return httpx.Response(200, json={'threadId': str(uuid.uuid4()), 'messages': [], 'turns': []})
        return httpx.Response(401, text='SECRET leaked by upstream')
    gateway = nod.Nod({'site': 'http://127.0.0.1:4310', 'token': 'SECRET'})
    monkeypatch.setattr(gateway, 'client', lambda: httpx.Client(base_url=gateway.url, headers={'Authorization': 'Bearer SECRET'}, transport=httpx.MockTransport(handler)))
    assert gateway.test()['conversation']
    with pytest.raises(HTTPException) as error:
        gateway.request('POST', '/api/messages', json={})
    assert 'SECRET' not in error.value.detail
    assert len(calls) == 3


def test_mock_requires_both_flags(monkeypatch):
    monkeypatch.setenv('HARQIS_NOD_MOCK', '1')
    monkeypatch.delenv('HFL_TIMELINE_LOCAL_PREVIEW', raising=False)
    with pytest.raises(HTTPException):
        nod_demo.connection('alice')


def test_projection_excludes_configuration_and_verification_secrets(linked, monkeypatch):
    raw = {'threadId': str(uuid.uuid4()), 'messages': [], 'turns': [],
           'configuration': {'llmReady': True, 'providerKey': 'SECRET'},
           'verificationRequests': [{'id': 'PRIVATE', 'kind': 'payment'}]}
    monkeypatch.setattr(nod_demo.MockNod, 'request', lambda *a, **kw: raw)
    view = nod.state('alice', linked['id'])
    assert view['needs_private_input'] and view['ready']
    assert 'SECRET' not in json.dumps(view) and 'PRIVATE' not in json.dumps(view)


def test_connector_routes_csrf_enable_disconnect(monkeypatch, tmp_path, authenticated_client):
    from modules.hfl_shares.security import make_csrf_token
    from modules.integrations import store
    monkeypatch.setenv('HARQIS_NOD_MOCK', '0')
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path/'connectors.sqlite3'))
    thread = str(uuid.uuid4())
    def handler(request):
        assert request.headers['authorization'] == 'Bearer PRIVATE-TOKEN'
        return httpx.Response(200, json={'ok': True} if request.url.path == '/api/health' else
                              {'threadId': thread, 'messages': [], 'turns': [], 'configuration': {'llmReady': True}})
    monkeypatch.setattr(nod.Nod, 'client', lambda self: httpx.Client(base_url=self.url, headers={'Authorization': 'Bearer '+self.key}, transport=httpx.MockTransport(handler)))
    client = authenticated_client
    headers = {'X-CSRF-Token': make_csrf_token('frontend-test-user')}
    prefix = '/integrations/api'
    raw = {'site': 'http://127.0.0.1:4310', 'token': 'PRIVATE-TOKEN'}
    assert client.post(prefix+'/connectors/nod/save', json=raw).status_code == 403
    response = client.post(prefix+'/connectors/nod/save', json=raw, headers=headers)
    assert response.status_code == 200 and 'PRIVATE-TOKEN' not in response.text
    assert client.post(prefix+'/nod/link', json={}, headers=headers).status_code == 409
    assert client.post(prefix+'/connectors/nod/toggle', json={'enabled': True}, headers=headers).status_code == 200
    linked = client.post(prefix+'/nod/link', json={}, headers=headers)
    assert linked.status_code == 200, linked.text
    identity = linked.json()['item']['id']
    assert client.get(prefix+'/nod/agents/'+identity+'/state').json()['thread_id'] == thread
    with store.connection() as db:
        assert 'PRIVATE-TOKEN' not in db.execute('SELECT credentials FROM connectors').fetchone()[0]
    client.post(prefix+'/connectors/nod/disconnect', json={}, headers=headers)
    assert client.get(prefix+'/nod/agents/'+identity+'/state').status_code == 409
