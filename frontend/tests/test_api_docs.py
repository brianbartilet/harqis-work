"""Complete documentation coverage, unchanged auth, and executable Swagger requests."""
import json
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from frontend.tests.test_agent_fleet import fleet, bridge


def test_docs_require_owner_login(authenticated_client):
    from main import app
    with TestClient(app) as anonymous:
        response = anonymous.get('/docs', follow_redirects=False)
        assert response.status_code == 302 and response.headers['location'] == '/login'
        assert anonymous.get('/openapi.json').status_code == 401
    page = authenticated_client.get('/docs')
    assert page.status_code == 200
    assert page.headers['cache-control'] == 'no-store'
    # Desktop and mobile navigation each render the shared Build menu.
    assert page.text.count('>API reference</a>') == 2
    assert '/static/vendor/swagger-ui-bundle-5.35.0.js?v=' in page.text
    assert '/static/js/api-docs.js?v=' in page.text
    assert 'cdn.jsdelivr.net' not in page.text


def test_combined_schema_preserves_all_operations_and_contracts(authenticated_client):
    from main import app
    from hfl_api import app as corpus
    before = json.dumps(app.openapi(), sort_keys=True)
    schema = authenticated_client.get('/openapi.json').json()
    assert set(schema['paths']) == set(app.openapi()['paths'])
    assert set(corpus.openapi()['paths']) <= set(schema['paths'])
    tags = {tag['name'] for tag in schema['tags']}
    ids = []
    for path, methods in app.openapi()['paths'].items():
        for method, operation in methods.items():
            documented = schema['paths'][path][method]
            assert documented['operationId'] == operation['operationId']
            assert documented['responses'] == operation['responses']
            assert documented['tags'][0] in tags
            ids.append(documented['operationId'])
    assert len(ids) == len(set(ids))
    assert schema['servers'] == [{'url': '/', 'description': 'Current HARQIS host (same origin)'}]
    assert json.dumps(app.openapi(), sort_keys=True) == before
    # Resolve every component reference after adding documentation metadata.
    def check(value):
        if isinstance(value, dict):
            ref = value.get('$ref', '')
            if ref.startswith('#/'):
                target = schema
                for key in ref[2:].split('/'):
                    target = target[key.replace('~1', '/').replace('~0', '~')]
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(schema)


def test_documented_auth_and_profile_example(authenticated_client):
    schema = authenticated_client.get('/openapi.json').json()
    paths = schema['paths']
    assert paths['/agents/api/items']['post']['security'] == [{'OwnerSession': []}]
    assert paths['/api/hfl/entries']['post']['security'] == [{'HTTPBearer': []}]
    assert paths['/api/hfl/entities/types']['post']['security'] == [{'OwnerSession': []}, {'HTTPBearer': []}]
    worker = [operation for path, methods in paths.items() if path.startswith('/api/hfl-agent/') for operation in methods.values()]
    assert worker and all(op['security'] == [{'BridgeToken': []}] for op in worker)
    example = paths['/agents/api/items']['post']['requestBody']['content']['application/json']['examples']['profile']['value']
    assert example['classification'] == 'workflows'
    assert 'version' in paths['/agents/api/items/{identity}']['post']['requestBody']['content']['application/json']['examples']['profile']['value']
    # Documentation does not relax the existing owner write boundary.
    assert authenticated_client.post('/agents/api/items', json=example).status_code == 403


def test_swagger_browser_reads_and_creates_profile(fleet, authenticated_client, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request):
            parsed = urlparse(request.request.url)
            response = client.request(request.request.method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                content=request.request.post_data_buffer,
                headers={key: value for key, value in request.request.headers.items() if key.lower() in {'content-type', 'x-csrf-token'}})
            request.fulfill(status=response.status_code, content_type=response.headers.get('content-type', 'text/html'), body=response.content)
        page.route('https://docs.test/**', route)
        page.goto('https://docs.test/docs')
        page.locator('.swagger-ui .filter-container input').wait_for()
        assert 'operations across' in page.locator('#api-docs-status').inner_text()
        page.locator('.swagger-ui .filter-container input').fill('Getting started')
        page.locator('.opblock-tag').filter(has_text='Getting started').click()
        health = page.locator('.opblock').filter(has=page.locator('[data-path="/health"]'))
        health.locator('.opblock-summary').click()
        health.get_by_role('button', name='Try it out').click()
        health.get_by_role('button', name='Execute', exact=True).click()
        playwright.expect(health.locator('.live-responses-table')).to_contain_text('200')
        playwright.expect(health.locator('.live-responses-table')).to_contain_text('ok')
        page.locator('.swagger-ui .filter-container input').fill('Agents · Fleet')
        page.locator('.opblock-tag').filter(has_text='Agents · Fleet').click()
        create = page.locator('.opblock-post').filter(has=page.locator('[data-path="/agents/api/items"]'))
        create.locator('.opblock-summary').click()
        create.get_by_role('button', name='Try it out').click()
        create.locator('textarea').fill(json.dumps({'name': 'Swagger test operator', 'classification': 'workflows'}))
        create.get_by_role('button', name='Execute', exact=True).click()
        playwright.expect(create.locator('.live-responses-table')).to_contain_text('200')
        assert any(agent['name'] == 'Swagger test operator' for agent in fleet.store().list())
        result = page.evaluate("""() => {
          const request = window.harqisDocsRequest({url: '/settings', method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: 'value=hello'});
          let blocked = false;
          try { window.harqisDocsRequest({url: 'https://elsewhere.test/', method: 'POST'}); } catch (_) { blocked = true; }
          return {csrf: !!request.headers['X-CSRF-Token'], form: !!new URLSearchParams(request.body).get('csrf'), blocked};
        }""")
        assert result == {'csrf': True, 'form': True, 'blocked': True}
        page.locator('.swagger-ui .filter-container input').fill('')
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(tmp_path / 'api-docs-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'api-docs-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
