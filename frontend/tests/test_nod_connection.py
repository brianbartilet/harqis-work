"""Nod health-only scaffold boundaries and owner credential handling."""
import json
from uuid import uuid4

import httpx
import pytest

from frontend.tests.test_primary_assistant import fleet, bridge, post, USER


@pytest.fixture
def nod_transport(monkeypatch, fleet):
    from modules.agents import nod_gateway
    original = httpx.Client
    calls, state = [], {'status': 200, 'body': {'ok': True}}

    def handle(request):
        calls.append(request)
        return httpx.Response(state['status'], json=state['body'])

    monkeypatch.setattr(nod_gateway.NodGateway, 'client', lambda self: original(
        base_url=self.url, headers={'Authorization': 'Bearer ' + self.key},
        transport=httpx.MockTransport(handle)))
    return calls, state


def settings():
    return {'enabled': True, 'version': 0, 'provider': 'nod', 'mode': 'setup',
            'url': 'http://localhost:4310', 'key': 'nod-owner-secret'}


def test_nod_setup_health_secrets_and_execution_boundary(nod_transport, authenticated_client):
    from modules.agents import connections
    client = authenticated_client
    agent = post(client, '/items', {'name': 'Mac Nod', 'runtime': 'nod'}).json()['item']
    path = '/items/' + agent['id']
    raw = settings()
    assert post(client, '/connections/test', raw).status_code == 200
    saved = post(client, path + '/connection', raw)
    assert saved.status_code == 200, saved.text
    assert saved.json()['mode'] == 'setup'
    assert saved.json()['capabilities']['run_submission'] is False
    assert 'nod-owner-secret' not in saved.text
    assert connections.read(USER, agent['id'], private=True)['key'] == raw['key']
    assert not connections.read('another-owner', agent['id'])['enabled']
    with connections.service.store().connect() as db:
        row = dict(db.execute('SELECT * FROM fleet_connections WHERE agent_id=?', (agent['id'],)).fetchone())
    assert raw['key'] not in json.dumps(row)
    assert raw['key'] not in client.get('/agents/api/items').text
    assert raw['key'] not in json.dumps(connections.service.store().events(agent['id']))
    assert client.get('/agents/api' + path + '/connection/status').json()['connected'] is True
    assert post(client, path + '/conversations', {'request_id': str(uuid4())}).status_code == 422
    assert post(client, path + '/connection', {**raw, 'version': 1, 'mode': 'execute'}).status_code == 422
    assert post(client, path + '/connection', {**raw, 'version': 1, 'provider': 'hermes'}).status_code == 422
    assert post(client, path + '/connection', {**raw, 'version': 1, 'key': ''}).status_code == 200
    assert post(client, path + '/connection', raw).status_code == 409
    assert post(client, path + '/connection', {**raw, 'version': 2, 'key': '', 'url': 'https://other.example'}).status_code == 422
    assert all(r.method == 'GET' and r.url.path == '/api/health' for r in nod_transport[0])
    assert all(r.headers['authorization'] == 'Bearer nod-owner-secret' for r in nod_transport[0])
    assert post(client, path + '/connection', {'enabled': False, 'version': 2}).status_code == 200
    assert not client.get('/agents/api' + path + '/connection').json()['has_key']


@pytest.mark.parametrize('status,body', [(401, {}), (403, {}), (302, {}), (200, {}), (200, {'ok': False}), (500, {'token': 'do-not-echo'})])
def test_nod_health_rejects_failed_or_wrong_contract(nod_transport, authenticated_client, status, body):
    nod_transport[1].update(status=status, body=body)
    response = post(authenticated_client, '/connections/test', settings())
    assert response.status_code == 502
    assert 'do-not-echo' not in response.text


@pytest.mark.parametrize('url', ['http://mac.local:4310', 'https://nod.example/path', 'https://user:secret@nod.example', 'https://nod.example?key=secret', 'https://nod.example:bad', 'javascript:alert(1)'])
def test_nod_invalid_origin_never_sends_token(nod_transport, authenticated_client, url):
    assert post(authenticated_client, '/connections/test', {**settings(), 'url': url}).status_code == 422
    assert not nod_transport[0]


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)])
def test_nod_browser_setup(nod_transport, authenticated_client, tmp_path, width, height):
    from urllib.parse import urlparse
    playwright = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.set_default_timeout(15000)
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
            page.get_by_label('Name', exact=True).fill('Mac Nod')
            page.get_by_label('Agent service', exact=True).select_option('nod')
            page.get_by_label('Connection mode', exact=True).select_option('server')
            page.get_by_label('Nod server URL', exact=True).fill('http://localhost:4310')
            page.get_by_label('Nod access token', exact=True).fill('nod-owner-secret')
            page.get_by_role('button', name='Test connection', exact=True).click()
            page.get_by_text('Nod server reachable · access verified. Chat and tasks remain in Nod.', exact=True).wait_for()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / 'nod-setup.png'))
            page.get_by_role('button', name='Save agent', exact=True).click()
            page.get_by_role('button', name='Select Mac Nod', exact=True).click()
            page.get_by_text('Nod server reachable · setup only', exact=True).wait_for()
            assert page.get_by_role('link', name='Open Nod', exact=True).get_attribute('href') == 'http://localhost:4310'
            assert page.get_by_role('button', name='Conversation', exact=True).count() == 0
            page.screenshot(path=str(tmp_path / 'nod-status.png'))
            page.get_by_role('button', name='Configure Nod', exact=True).click()
            assert page.get_by_label('Nod access token', exact=True).input_value() == ''
            assert page.get_by_label('Nod access token', exact=True).get_attribute('placeholder') == 'Saved · leave blank to keep'
            page.get_by_label('Connection mode', exact=True).select_option('profile')
            page.get_by_role('button', name='Save agent', exact=True).click()
            page.get_by_text('Nod server not configured.', exact=True).wait_for()
            assert page.get_by_role('link', name='Open Nod', exact=True).count() == 0
            assert not errors, errors
        finally:
            browser.close()
