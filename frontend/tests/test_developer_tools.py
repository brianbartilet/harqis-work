import json
import sys
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from frontend.tests.test_agent_fleet import fleet, bridge


def test_mcp_catalogue_reads_source_without_importing_apps(tmp_path, monkeypatch):
    import developer_tools as hub
    source = tmp_path / 'apps/example/mcp.py'
    source.parent.mkdir(parents=True)
    source.write_text('''raise RuntimeError("Do not import this module")
def register(mcp):
    @mcp.tool(name="read_example")
    def read(identity: str, limit: int = 10):
        """Read an example record."""
        raise RuntimeError("Do not call tools")
''')
    monkeypatch.setattr(hub, 'ROOT', tmp_path)
    monkeypatch.setattr(hub, 'APP_CATALOG', [SimpleNamespace(key='example', label='Example', registrar='apps.example.mcp.register')])
    before = set(sys.modules)
    app = hub.mcp_catalogue()[0]
    assert app['tools'] == [{'name': 'read_example', 'description': 'Read an example record.', 'signature': 'read_example(identity: str, limit: int=10)'}]
    assert not (set(sys.modules) - before)
    (source.parent / 'README.md').write_text('# Example\n\nA [useful API](https://example.test/docs) for\nreading **records**.\n\n```\ninternal/path\n```')
    assert hub.mcp_catalogue()[0]['description'] == 'A useful API for reading records.'
    source.write_text('broken source !')
    assert hub.mcp_catalogue()[0]['note'] == 'Source documentation is unavailable for this app.'


def test_hub_authentication_and_runtime_catalogue(authenticated_client):
    import developer_tools as hub
    from tools.catalog import APP_CATALOG
    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as anonymous:
        assert anonymous.get('/developer-tools', follow_redirects=False).status_code == 302
    response = authenticated_client.get('/developer-tools')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert '/static/js/developer-tools.js?v=' in response.text
    assert 'href="/docs"' in response.text
    assert 'stdio' in response.text and 'not a live MCP connection' in response.text
    apps = hub.mcp_catalogue()
    assert len(apps) == len(APP_CATALOG)
    jira = next(app for app in apps if app['key'] == 'jira')
    assert any(tool['name'] == 'get_jira_issue' for tool in jira['tools'])
    assert '/developer-tools' not in authenticated_client.get('/openapi.json').json()['paths']


def test_documentation_routes_have_reviewed_mcp_classification():
    from tools.frontend_coverage import inventory, MANIFEST
    actual = inventory()
    rows = {(row['method'], row['path']): row for row in json.loads(MANIFEST.read_text())['endpoints']}
    for path in ('/docs', '/openapi.json', '/developer-tools'):
        assert ('GET', path) in actual
        assert rows['GET', path]['status'] == 'ui'


def test_developer_hub_browser(fleet, authenticated_client, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request):
            parsed = urlparse(request.request.url)
            response = authenticated_client.request(request.request.method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                content=request.request.post_data_buffer,
                headers={key: value for key, value in request.request.headers.items() if key.lower() in {'content-type', 'x-csrf-token'}})
            request.fulfill(status=response.status_code, content_type=response.headers.get('content-type', 'text/html'), body=response.content)
        page.route('https://docs.test/**', route)
        page.goto('https://docs.test/developer-tools')
        playwright.expect(page.locator('#http-api')).to_be_visible()
        playwright.expect(page.locator('#mcp-server')).to_be_hidden()
        playwright.expect(page.locator('#mcp-tools')).to_be_hidden()
        playwright.expect(page.locator('.developer-app')).to_have_count(12)
        page.get_by_role('button', name='Build', exact=True).filter(visible=True).click()
        playwright.expect(page.get_by_role('link', name='Developer Resources', exact=True).filter(visible=True)).to_be_visible()
        page.get_by_role('button', name='Build', exact=True).filter(visible=True).click()
        page.get_by_role('tab', name='HTTP API').focus()
        page.keyboard.press('End')
        playwright.expect(page.get_by_role('tab', name='Tool catalogue')).to_be_focused()
        playwright.expect(page.locator('#mcp-tools')).to_be_visible()
        assert page.url.endswith('#mcp-tools')
        page.get_by_role('button', name='Show more apps').click()
        playwright.expect(page.locator('.developer-app')).to_have_count(24)
        page.get_by_label('Find an app or tool').fill('get_jira_issue')
        tool = page.locator('.developer-tool').filter(has=page.get_by_text('get_jira_issue', exact=True))
        tool.locator('summary').click()
        playwright.expect(tool.locator('pre')).to_contain_text('issue_key: str')
        page.get_by_role('tab', name='MCP server', exact=True).click()
        page.get_by_role('tab', name='Tool catalogue').click()
        playwright.expect(page.get_by_label('Find an app or tool')).to_have_value('get_jira_issue')
        page.get_by_label('Find an app or tool').fill('no-such-tool-987654')
        playwright.expect(page.locator('#mcp-catalogue-status')).to_contain_text('No apps or tools match')
        page.get_by_label('Find an app or tool').fill('')
        page.get_by_role('tab', name='MCP server', exact=True).click()
        page.get_by_role('button', name='Windows', exact=True).click()
        playwright.expect(page.locator('#mcp-client-config')).to_contain_text('python.exe')
        gap = page.locator('#mcp-client-config').evaluate("node => node.getBoundingClientRect().top - document.querySelector('.developer-platforms').getBoundingClientRect().bottom")
        assert gap >= 16
        page.get_by_role('tab', name='Tool catalogue').click()
        page.evaluate('window.scrollTo(0, 0)')
        cards = page.locator('.developer-app>summary')
        assert cards.nth(1).bounding_box()['x'] > cards.nth(0).bounding_box()['x']
        assert page.locator('.developer-app-description').first.inner_text()
        page.screenshot(path=str(tmp_path / 'developer-hub-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'developer-hub-mobile.png'))
        page.locator('#mcp-tools').scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / 'developer-hub-catalogue-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.reload()
        playwright.expect(page.locator('#mcp-tools')).to_be_visible()
        assert not errors, errors
        browser.close()
