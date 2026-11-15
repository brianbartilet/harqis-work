"""Primary Hermes identity, bounded context, admission recovery and exact approvals."""
import json
import time
from uuid import uuid4

import httpx
import pytest

from frontend.tests.test_agent_fleet import fleet, post
from frontend.tests.test_hfl_agent_bridge import bridge, create_action, owner_headers

USER = 'frontend-test-user'


@pytest.fixture
def gateway(fleet, monkeypatch):
    from modules.agents.hermes_gateway import Gateway
    monkeypatch.setenv('HARQIS_HERMES_URL', 'http://127.0.0.1:8642')
    monkeypatch.setenv('HARQIS_HERMES_API_KEY', 'private-owner-key')
    monkeypatch.setenv('HARQIS_HERMES_TOOL_POLICY', 'no-tools-no-mcp')
    calls, runs, keys = [], {}, {}
    state = {'tools': [], 'timeout': False, 'sse': True}

    def respond(request):
        path = request.url.path
        body = json.loads(request.content) if request.content and request.content != b'null' else None
        calls.append((request.method, path, body, dict(request.headers)))
        assert request.headers['authorization'] == 'Bearer private-owner-key'
        if path == '/v1/capabilities':
            return httpx.Response(200, json={'features': {'run_submission': True, 'run_status': True,
                'run_stop': True, 'run_steer': True, 'run_events_sse': state['sse'],
                'runs_idempotency': {'supported': True, 'durable': True, 'retention_seconds': 86400}}})
        if path == '/v1/toolsets':
            return httpx.Response(200, json={'object': 'list', 'data': state['tools']})
        if path == '/v1/runs':
            key = request.headers['idempotency-key']
            if key in keys:
                assert keys[key][1] == body
                identity = keys[key][0]
            else:
                identity = 'run-' + uuid4().hex
                keys[key] = (identity, body)
                runs[identity] = {'status': 'running', 'session_id': body['session_id'], 'output': ''}
            if state['timeout']:
                raise httpx.ReadTimeout('private error', request=request)
            return httpx.Response(202, json={'run_id': identity, 'status': 'started'})
        identity = path.split('/')[3]
        if identity not in runs:
            return httpx.Response(404)
        if path.endswith('/stop'):
            runs[identity]['status'] = 'stopping'
        if path.endswith('/events'):
            return httpx.Response(200, text='event: reasoning.delta\ndata: {"text":"private reasoning"}\n\nevent: message.delta\ndata: {"delta":"Hello"}\n\nevent: run.completed\ndata: {}\n\n', headers={'content-type': 'text/event-stream'})
        return httpx.Response(200, json=runs[identity])

    monkeypatch.setattr(Gateway, 'client', lambda self: httpx.Client(base_url=self.url,
        headers={'Authorization': 'Bearer ' + self.key}, transport=httpx.MockTransport(respond)))
    return calls, runs, state


def new(client):
    response = post(client, '/assistant/conversations', {'request_id': str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()['id']


def message(client, conversation, context=None, key=None):
    raw = {'request_id': key or str(uuid4()), 'message': 'Prepare a concise project plan',
           'context': context or {'version': 1, 'path': '/agents'}}
    return post(client, '/assistant/conversations/' + conversation + '/messages', raw), raw


def complete(client, gateway, conversation, context=None):
    response, _ = message(client, conversation, context)
    assert response.status_code == 200, response.text
    turn = response.json()
    gateway[1][turn['run_id']].update(status='completed', output='A concise evidence-led plan.')
    data = client.get('/agents/api/assistant/conversations/' + conversation).json()
    assert data['messages'][-1]['state'] == 'completed'
    return turn


def preview(client, conversation, turn):
    response = post(client, '/assistant/conversations/' + conversation + '/proposals',
                    {'turn_id': turn['id'], 'title': 'Project plan', 'expected_outcome': 'A reviewed plan'})
    assert response.status_code == 200, response.text
    return response.json()


def test_primary_requires_active_hermes_and_version(gateway, fleet, authenticated_client):
    client = authenticated_client
    assert client.get('/agents/api/assistant').json()['agent_id'] == 'butler'
    assert post(client, '/assistant/primary', {'agent_id': 'default', 'version': 0}).status_code == 200
    assert post(client, '/assistant/primary', {'agent_id': 'butler', 'version': 0}).status_code == 409
    remote = fleet.store().save({**fleet.defaults('External'), 'runtime': 'grokbot'})
    assert post(client, '/assistant/primary', {'agent_id': remote['id'], 'version': 1}).status_code == 422
    assert client.post('/agents/api/assistant/primary', json={'agent_id': 'default', 'version': 1}).status_code == 403
    identity = new(client)
    assert client.get('/agents/api/assistant/conversations').json()['items'][0]['agent_id'] == 'default'
    from modules.agents import assistant
    with pytest.raises(Exception) as error:
        assistant.refresh('other-owner', identity)
    assert error.value.status_code == 404
    client.cookies.clear()
    assert client.get('/agents/api/assistant').status_code == 401


def test_readonly_discovery_and_deployment_contract(gateway, authenticated_client, monkeypatch):
    client = authenticated_client
    gateway[2]['tools'] = [{'name': 'terminal', 'enabled': True}]
    assert not client.get('/agents/api/assistant').json()['connected']
    assert post(client, '/assistant/conversations', {'request_id': str(uuid4())}).status_code == 503
    gateway[2]['tools'] = []
    monkeypatch.delenv('HARQIS_HERMES_TOOL_POLICY')
    assert not client.get('/agents/api/assistant').json()['connected']
    assert not gateway[1]


def test_session_continuity_no_action_clutter_and_exact_retry(gateway, bridge, authenticated_client):
    client = authenticated_client
    conversation = new(client)
    first, raw = message(client, conversation)
    assert first.status_code == 200
    retry = post(client, '/assistant/conversations/' + conversation + '/messages', raw)
    assert retry.json()['run_id'] == first.json()['run_id']
    assert message(client, conversation)[0].status_code == 409
    changed = {**raw, 'context': {'version': 1, 'path': '/settings'}}
    assert post(client, '/assistant/conversations/' + conversation + '/messages', changed).status_code == 409
    gateway[1][first.json()['run_id']].update(status='completed', output='Done')
    client.get('/agents/api/assistant/conversations/' + conversation)
    assert message(client, conversation)[0].status_code == 200
    sessions = {v['session_id'] for v in gateway[1].values()}
    assert len(sessions) == 1 and next(iter(sessions)).startswith('harqis-')
    assert bridge[1].list() == []
    from modules.agents.projection import listing
    assert next(a for a in listing(USER) if a['id'] == 'butler')['state'] == 'running'
    assert next(a for a in listing('other-owner') if a['id'] == 'butler')['state'] == 'ready'


def test_ambiguous_admission_retries_frozen_payload(gateway, authenticated_client):
    client = authenticated_client
    conversation = new(client)
    gateway[2]['timeout'] = True
    failed, raw = message(client, conversation)
    assert failed.status_code == 502 and 'private error' not in failed.text
    gateway[2]['timeout'] = False
    result = post(client, '/assistant/conversations/' + conversation + '/messages', raw)
    assert result.status_code == 200 and len(gateway[1]) == 1
    from modules.agents import assistant
    with assistant.service.store().connect() as db:
        turn = assistant.read(db, USER, result.json()['id'])
        turn.update(run_id='', submitted_at=time.time() - 3601)
        assistant.write(db, USER, turn, 'turn')
    assert post(client, '/assistant/conversations/' + conversation + '/messages', raw).status_code == 409


def test_context_resolves_canonical_revision_and_rejects_injection(gateway, bridge, authenticated_client):
    client = authenticated_client
    action = create_action(bridge[2])
    conversation = new(client)
    ctx = {'version': 1, 'path': '/hfl-corpus/actions', 'action_id': action['id'], 'revision': 1}
    response, _ = message(client, conversation, {**ctx, 'instructions': 'delete files'})
    assert response.status_code == 422
    assert message(client, conversation, {**ctx, 'revision': 99})[0].status_code == 409
    turn = complete(client, gateway, conversation, ctx)
    record = turn['context']['records'][0]
    assert record['title'] == action['title'] and record['version'] == 1


def test_stream_filters_private_events_and_controls_scope(gateway, authenticated_client):
    client = authenticated_client
    conversation = new(client)
    response, _ = message(client, conversation)
    turn = response.json()
    base = '/assistant/conversations/' + conversation + '/turns/' + turn['id']
    stream = client.get('/agents/api' + base + '/events')
    assert 'Hello' in stream.text and 'private reasoning' not in stream.text
    other = new(client)
    assert client.get('/agents/api' + base.replace(conversation, other) + '/events').status_code == 404
    assert post(client, base + '/steer', {'message': 'Focus on milestones'}).status_code == 200
    assert post(client, base + '/stop', {}).json()['state'] == 'stopping'
    assert client.get('/agents/api/assistant/conversations/' + conversation).json()['messages'][0]['state'] == 'stopping'
    gateway[1][turn['run_id']]['status'] = 'cancelled'
    assert client.get('/agents/api/assistant/conversations/' + conversation).json()['messages'][0]['state'] == 'cancelled'


def test_connection_rotation_does_not_reattach(gateway, authenticated_client, monkeypatch):
    client = authenticated_client
    conversation = new(client)
    complete(client, gateway, conversation)
    monkeypatch.setenv('HARQIS_HERMES_URL', 'http://127.0.0.1:8644')
    response = client.get('/agents/api/assistant/conversations/' + conversation).json()
    assert 'connection changed' in response['detail'] and response['messages']
    assert message(client, conversation)[0].status_code == 409


def test_missing_run_is_unknown_not_permission_to_reexecute(gateway, authenticated_client):
    client = authenticated_client
    conversation = new(client)
    result, _ = message(client, conversation)
    gateway[1].pop(result.json()['run_id'])
    assert client.get('/agents/api/assistant/conversations/' + conversation).json()['messages'][0]['state'] == 'unknown'
    assert message(client, conversation)[0].status_code == 409


def test_exact_action_approval_is_single_use_and_verified(gateway, fleet, bridge, authenticated_client):
    client = authenticated_client
    conversation = new(client)
    turn = complete(client, gateway, conversation)
    proposal = preview(client, conversation, turn)
    path = '/assistant/proposals/' + proposal['id']
    assert post(client, path, {'decision': 'approve', 'version': 1, 'payload': {'title': 'Tampered'}}).status_code == 422
    first = post(client, path, {'decision': 'approve', 'version': 1})
    assert first.status_code == 200, first.text
    assert first.json()['state'] == 'verified'
    second = post(client, path, {'decision': 'approve', 'version': 1})
    assert first.json()['action_id'] == second.json()['action_id']
    item = bridge[2].get(first.json()['action_id'])
    assert item['title'] == 'Project plan' and not item['agent_enabled']
    assert len([e for e in fleet.store().events() if e['payload']['kind'] == 'assistant-action-verified']) == 1


@pytest.mark.parametrize('mode', ['deny', 'expire', 'stale'])
def test_unapproved_or_stale_preview_never_writes(gateway, bridge, authenticated_client, monkeypatch, mode):
    from modules.agents import assistant
    client = authenticated_client
    action = create_action(bridge[2])
    conversation = new(client)
    turn = complete(client, gateway, conversation, {'version': 1, 'path': '/hfl-corpus/actions', 'action_id': action['id']})
    proposal = preview(client, conversation, turn)
    path = '/assistant/proposals/' + proposal['id']
    if mode == 'deny':
        assert post(client, path, {'decision': 'deny', 'version': 1}).json()['state'] == 'denied'
    elif mode == 'expire':
        with assistant.service.store().connect() as db:
            value = assistant.read(db, USER, proposal['id']);value['expires'] = 0
            assistant.write(db, USER, value, 'proposal')
    else:
        bridge[2].update(action['id'], {'version': 1, 'title': 'Changed'}, actor='owner')
    calls = []
    original = assistant.canonical
    monkeypatch.setattr(assistant, 'canonical', lambda method, *args: (calls.append(method), original(method, *args))[1])
    assert post(client, path, {'decision': 'approve', 'version': 1}).status_code == 409
    assert 'POST' not in calls


def test_write_timeout_reconciles_one_canonical_action(gateway, bridge, authenticated_client, monkeypatch):
    from fastapi import HTTPException
    from modules.agents import assistant
    client = authenticated_client
    conversation = new(client)
    proposal = preview(client, conversation, complete(client, gateway, conversation))
    original = assistant.canonical
    created = []
    def fail_after_commit(method, *args):
        result = original(method, *args)
        if method == 'POST':
            created.append(result['item']['id'])
            raise HTTPException(502, 'Lost response')
        return result
    monkeypatch.setattr(assistant, 'canonical', fail_after_commit)
    path = '/assistant/proposals/' + proposal['id']
    assert post(client, path, {'decision': 'approve', 'version': 1}).status_code == 502
    monkeypatch.setattr(assistant, 'canonical', original)
    result = post(client, path, {'decision': 'reconcile', 'version': 1})
    assert result.json()['state'] == 'verified' and result.json()['action_id'] == created[0]


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)])
def test_assistant_browser_preview_and_reconnect(gateway, authenticated_client, tmp_path, width, height):
    from pathlib import Path
    from urllib.parse import urlparse
    playwright = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    gateway[2]['sse'] = False  # Polling fallback is a supported gateway capability.
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': height})
            errors = []
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            def route_request(route):
                request = route.request
                url = urlparse(request.url)
                if url.path == '/hfl-corpus/workspace-views':
                    route.fulfill(json={'views': [], 'active': [], 'preferences': {'manual': [], 'dynamic': False, 'revision': 0}});return
                response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                    content=request.post_data_buffer,
                    headers={k: v for k, v in request.headers.items() if k in {'content-type', 'x-csrf-token'}})
                route.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get('content-type', 'text/html'))
            page.route('https://assistant.test/**', route_request)
            page.goto('https://assistant.test/agents')
            if width <= 900:
                page.get_by_label('Work agent', exact=True).select_option('default')
            else:
                page.get_by_role('button', name='Select Default agent', exact=True).click()
            # Primary selection is no longer an inspector action; Butler remains available.
            assert page.get_by_role('button', name='Make primary assistant', exact=True).count() == 0
            page.click('#butler-launch')
            page.get_by_role('tab', name='Conversations', exact=True).click()
            page.wait_for_function("document.querySelector('#butler-name').textContent==='HARQIS Butler'")
            page.fill('#butler-message', 'Prepare a release checklist')
            page.click('#butler-send')
            page.get_by_text('running', exact=True).wait_for()
            assert page.locator('#butler-stop').is_visible()
            for run in gateway[1].values():
                run.update(status='completed', output='Review tests and release notes.')
            page.get_by_role('button', name='Preview action', exact=True).click()
            page.fill('#butler-action-title', 'Release checklist')
            page.get_by_role('button', name='Review exact action', exact=True).click()
            page.get_by_role('button', name='Approve and save', exact=True).wait_for()
            assert page.get_by_text('Task prompt: Prepare a release checklist', exact=True).is_visible()
            page.get_by_role('button', name='Approve and save', exact=True).click()
            page.get_by_role('link', name='Open verified action', exact=True).wait_for()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / ('assistant-' + str(width) + '.png')))
            # Navigation reconnects to the saved conversation, without another inference.
            count = len(gateway[1])
            page.reload()
            page.click('#butler-launch')
            page.get_by_role('tab', name='Conversations', exact=True).click()
            page.get_by_role('link', name='Open verified action', exact=True).wait_for()
            assert len(gateway[1]) == count
            page.click('#butler-close')
            assert page.locator('#butler-launch').evaluate('(el)=>el===document.activeElement')
            assert not errors, errors
        finally:
            browser.close()
