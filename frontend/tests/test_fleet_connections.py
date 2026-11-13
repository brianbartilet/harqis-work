"""Per-agent gateway configuration and persistent, isolated fleet conversations."""
import json
from uuid import uuid4

import pytest
from frontend.tests.test_primary_assistant import gateway, fleet, bridge, post, message, USER
from frontend.tests.test_hfl_agent_bridge import owner_headers


def configured(client, *, mode='chat', name='Gateway agent'):
    agent = post(client, '/items', {'name': name, 'runtime': 'hermes'}).json()['item']
    raw = {'enabled': True, 'version': 0, 'url': 'http://127.0.0.1:8642', 'key': 'private-owner-key',
           'mode': mode, 'readonly_confirmed': mode == 'chat'}
    response = post(client, '/items/' + agent['id'] + '/connection', raw)
    assert response.status_code == 200, response.text
    return agent, raw, response.json()


def conversation(client, agent):
    result = post(client, '/items/' + agent['id'] + '/conversations', {'request_id': str(uuid4())})
    assert result.status_code == 200, result.text
    return result.json()['id']


def test_connection_secrets_encrypted_and_scoped(gateway, fleet, authenticated_client):
    from modules.agents import connections
    client = authenticated_client
    agent, raw, saved = configured(client)
    assert saved['has_key'] and saved['version'] == 1
    assert 'private-owner-key' not in json.dumps(saved)
    assert 'private-owner-key' not in client.get('/agents/api/items').text
    assert 'private-owner-key' not in json.dumps(fleet.store().events(agent['id']))
    with fleet.store().connect() as db:
        record = dict(db.execute('SELECT * FROM fleet_connections WHERE agent_id=?', (agent['id'],)).fetchone())
    assert 'private-owner-key' not in json.dumps(record)
    assert not connections.read('different-owner', agent['id'])['enabled']
    assert connections.read(USER, agent['id'], private=True)['key'] == 'private-owner-key'
    assert client.post('/agents/api/items/' + agent['id'] + '/connection', json=raw).status_code == 403
    assert post(client, '/items/' + agent['id'] + '/connection', raw).status_code == 409
    # Empty key preserves only this saved endpoint's credential.
    raw.update(version=1, key='')
    assert post(client, '/items/' + agent['id'] + '/connection', raw).status_code == 200
    raw.update(version=2, url='https://another.example')
    assert post(client, '/items/' + agent['id'] + '/connection', raw).status_code == 422


def test_readonly_mode_and_unsupported_services(gateway, authenticated_client):
    client = authenticated_client
    raw = {'enabled': True, 'version': 0, 'url': 'http://127.0.0.1:8642', 'key': 'private-owner-key',
           'mode': 'chat', 'readonly_confirmed': False}
    assert post(client, '/connections/test', raw).status_code == 422
    raw['readonly_confirmed'] = True
    gateway[2]['tools'] = [{'name': 'terminal', 'enabled': True}]
    assert post(client, '/connections/test', raw).status_code == 503
    raw['mode'] = 'execute'
    assert post(client, '/connections/test', raw).status_code == 200
    nod = post(client, '/items', {'name': 'Nod', 'runtime': 'nod'}).json()['item']
    assert post(client, '/items/' + nod['id'] + '/connection', raw).status_code == 422
    assert post(client, '/items/' + nod['id'] + '/conversations', {'request_id': str(uuid4())}).status_code == 422


@pytest.mark.parametrize('url', ['http://example.com', 'https://user:password@example.com',
                              'https://example.com/path', 'https://example.com?key=secret', 'file:///tmp'])
def test_invalid_gateway_addresses(gateway, authenticated_client, url):
    raw = {'enabled': True, 'version': 0, 'url': url, 'key': 'private-owner-key', 'mode': 'execute'}
    assert post(authenticated_client, '/connections/test', raw).status_code == 503
    assert not gateway[0]


def test_fleet_task_lifecycle_and_primary_chat_remains_separate(gateway, fleet, authenticated_client):
    client = authenticated_client
    gateway[2]['tools'] = [{'name': 'terminal', 'enabled': True}]
    agent, _, _ = configured(client, mode='execute')
    identity = conversation(client, agent)
    response, raw = message(client, identity)
    assert response.status_code == 200, response.text
    turn = response.json()
    submitted = next(call[2] for call in gateway[0] if call[1] == '/v1/runs')
    assert 'configured on this gateway' in submitted['instructions']
    assert json.loads(submitted['input'])['context']['records'] == []
    assert 'agent_activity' not in submitted['input']
    assert client.get('/agents/api/assistant/conversations').json()['items'] == []
    assert client.get('/agents/api/items/' + agent['id'] + '/conversations').json()['items'][0]['id'] == identity
    # Default Butler still refuses a tool-enabled platform.
    assert post(client, '/assistant/conversations', {'request_id': str(uuid4())}).status_code == 503
    prefix = '/assistant/conversations/' + identity + '/turns/' + turn['id']
    assert post(client, prefix + '/steer', {'message': 'Include a summary'}).status_code == 200
    events = client.get('/agents/api' + prefix + '/events').text
    assert 'Hello' in events and 'private reasoning' not in events
    assert post(client, prefix + '/stop', {}).status_code == 200
    gateway[1][turn['run_id']].update(status='cancelled', output='Stopped by the owner.')
    result = client.get('/agents/api/assistant/conversations/' + identity).json()
    assert result['messages'][0]['state'] == 'cancelled'
    assert result['mode'] == 'execute'
    assert result['messages'][0]['answer'] == 'Stopped by the owner.'


def test_timeout_replays_same_run_and_connection_change_blocks_old_session(gateway, authenticated_client):
    client = authenticated_client
    agent, settings, saved = configured(client)
    identity = conversation(client, agent)
    gateway[2]['timeout'] = True
    response, raw = message(client, identity)
    assert response.status_code == 502
    assert len(gateway[1]) == 1
    gateway[2]['timeout'] = False
    retry = post(client, '/assistant/conversations/' + identity + '/messages', raw)
    assert retry.status_code == 200 and len(gateway[1]) == 1
    assert post(client, '/items/' + agent['id'] + '/connection', {**settings, 'version': saved['version'], 'mode': 'execute'}).status_code == 200
    old = client.get('/agents/api/assistant/conversations/' + identity).json()
    assert old['connected'] is False and 'connection changed' in old['detail']
    assert post(client, '/assistant/conversations/' + identity + '/messages', raw).status_code == 409


def test_disconnect_preserves_history_and_blocks_execution(gateway, authenticated_client):
    client = authenticated_client
    agent, _, saved = configured(client)
    identity = conversation(client, agent)
    response, _ = message(client, identity)
    assert response.status_code == 200
    assert post(client, '/items/' + agent['id'] + '/connection', {'enabled': False, 'version': saved['version']}).status_code == 200
    data = client.get('/agents/api/assistant/conversations/' + identity).json()
    assert len(data['messages']) == 1 and data['connected'] is False
    assert client.get('/agents/api/items/' + agent['id'] + '/connection').json()['has_key'] is False
    assert post(client, '/items/' + agent['id'] + '/conversations', {'request_id': str(uuid4())}).status_code == 409


def test_conversation_owner_agent_and_capability_boundaries(gateway, authenticated_client, monkeypatch):
    from modules.agents import assistant
    from modules.agents.hermes_gateway import Gateway
    client = authenticated_client
    first, _, _ = configured(client)
    second, _, _ = configured(client, name='Second agent')
    identity = conversation(client, first)
    assert client.get('/agents/api/items/' + second['id'] + '/conversations').json()['items'] == []
    with pytest.raises(Exception) as error:
        assistant.refresh('different-owner', identity)
    assert error.value.status_code == 404
    result, _ = message(client, identity)
    turn = result.json()
    monkeypatch.setattr(Gateway, 'capabilities', lambda self, **kwargs: {'run_stop': False, 'run_steer': False, 'run_events_sse': False})
    assert post(client, '/assistant/conversations/' + identity + '/turns/' + turn['id'] + '/stop', {}).status_code == 409
    assert client.get('/agents/api/assistant/conversations/' + identity + '/turns/' + turn['id'] + '/events').status_code == 409
    assert post(client, '/items/' + first['id'], {'version': first['version'], 'active': False}).status_code == 200
    assert post(client, '/items/' + first['id'] + '/conversations', {'request_id': str(uuid4())}).status_code == 409


def test_chat_rechecks_gateway_policy_before_sending(gateway, authenticated_client):
    client = authenticated_client
    agent, _, _ = configured(client)
    identity = conversation(client, agent)
    gateway[2]['tools'] = [{'name': 'terminal', 'enabled': True}]
    response, _ = message(client, identity)
    assert response.status_code == 503
    assert gateway[1] == {}


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)])
def test_gateway_browser_setup_and_conversation(gateway, authenticated_client, tmp_path, width, height):
    from urllib.parse import urlparse
    playwright = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    gateway[2]['sse'] = False
    gateway[2]['tools'] = [{'name': 'terminal', 'enabled': True}]
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': height})
            errors = []
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            def route_request(route):
                request, url = route.request, urlparse(route.request.url)
                if url.path == '/hfl-corpus/workspace-views':
                    route.fulfill(json={'views': [], 'active': [], 'preferences': {'dynamic': False}})
                    return
                if url.path == '/agents/hud/data':
                    route.fulfill(json={'layout': {'widgets': []}, 'items': {}, 'context': [], 'spaces': {'views': []}})
                    return
                response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                    content=request.post_data_buffer,
                    headers={k: v for k, v in request.headers.items() if k in {'content-type', 'x-csrf-token'}})
                route.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get('content-type', 'text/html'))
            page.route('https://fleet-gateway.test/**', route_request)
            page.goto('https://fleet-gateway.test/agents')
            page.get_by_role('button', name='+ Add agent', exact=True).click()
            page.get_by_label('Name', exact=True).fill('Connected agent')
            page.get_by_label('Connection mode', exact=True).select_option('gateway')
            page.get_by_label('Gateway URL', exact=True).fill('http://127.0.0.1:8642')
            page.get_by_label('Gateway API key', exact=True).fill('private-owner-key')
            page.get_by_label('Interaction support', exact=True).select_option('execute')
            page.get_by_role('button', name='Test connection', exact=True).click()
            page.get_by_text('Connected · task execution · stop, steering', exact=True).wait_for()
            page.screenshot(path=str(tmp_path / 'gateway-setup.png'))
            page.get_by_role('button', name='Save agent', exact=True).click()
            page.get_by_role('button', name='Select Connected agent', exact=True).click()
            page.get_by_role('tab', name='Conversation', exact=True).click()
            panel = page.get_by_role('region', name='Conversation with Connected agent', exact=True)
            panel.get_by_role('button', name='New conversation', exact=True).click()
            panel.get_by_label('Message to agent', exact=True).fill('Prepare a report')
            panel.get_by_role('button', name='Run task', exact=True).click()
            panel.get_by_text('running', exact=True).wait_for()
            panel.get_by_label('Message to agent', exact=True).fill('Include references')
            panel.get_by_role('button', name='Steer', exact=True).click()
            panel.get_by_role('button', name='Stop', exact=True).click()
            for run in gateway[1].values():
                run.update(status='cancelled', output='Stopped after preparing the outline.')
            panel.get_by_text('Stopped after preparing the outline.', exact=True).wait_for()
            panel.get_by_role('button', name='Expand', exact=True).click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / 'gateway-conversation.png'))
            page.keyboard.press('Escape')
            assert panel.get_by_role('button', name='Expand', exact=True).evaluate('(el)=>el===document.activeElement')
            count = len(gateway[1])
            page.reload()
            page.get_by_role('button', name='Select Connected agent', exact=True).click()
            page.get_by_role('tab', name='Conversation', exact=True).click()
            panel.get_by_text('Stopped after preparing the outline.', exact=True).wait_for()
            assert len(gateway[1]) == count
            panel.get_by_role('button', name='Connection settings', exact=True).click()
            assert page.get_by_label('Gateway API key', exact=True).input_value() == ''
            assert page.get_by_label('Gateway API key', exact=True).get_attribute('placeholder') == 'Saved · leave blank to keep'
            page.get_by_label('Connection mode', exact=True).select_option('bridge')
            page.get_by_role('button', name='Save agent', exact=True).click()
            panel.get_by_text('Gateway not configured', exact=True).wait_for()
            assert panel.get_by_role('button', name='New conversation', exact=True).is_disabled()
            assert not errors, errors
        finally:
            browser.close()
