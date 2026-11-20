"""Agent connector grouping, managed defaults and installation identity."""
import json
from pathlib import Path

import pytest
from jinja2 import Environment
from test_control_focus_browser import browser
from test_agent_fleet import fleet
from test_hfl_agent_bridge import bridge

ROOT = Path(__file__).resolve().parents[1]


def test_openclaw_link_is_owner_scoped_and_preserves_profile(fleet, monkeypatch):
    from modules.integrations import openclaw, store
    from modules.agents import entities
    monkeypatch.setattr(openclaw, 'openclaw_health', lambda: None)
    for user in ('one', 'two'):
        store.save(user, 'openclaw', {**openclaw.OpenClaw(openclaw.credentials({})).test(),
                   'enabled': True, 'status': 'Connected'}, openclaw.credentials({}))
    first = openclaw.link('one', {})['item']
    fleet.store().save({**first, 'name': 'My assistant'}, identity=first['id'], version=first['version'])
    assert openclaw.link('one', {})['item']['name'] == 'My assistant'
    assert openclaw.link('two', {})['item']['id'] != first['id']
    assert len(entities.snapshot('one')['items']) == 1
    assert store.get('one', 'hermes')['managed'] is True


@pytest.mark.parametrize('width', [390, 1440])
def test_agents_default_and_connector_tabs(browser, width, tmp_path):
    from modules.integrations.service import PROVIDERS
    template = Environment().from_string((ROOT / 'templates/modules/applications/connectors.html').read_text('utf-8'))
    html = template.render(integration_csrf='', applications=[], static_asset=lambda path: '/static/' + path)
    html = '<link rel="stylesheet" href="/static/css/app.min.css"><body style="background:#020617;color:#e2e8f0;padding:16px;font-family:Arial,sans-serif">' + html
    html += '<section id="workflow-integrations" hidden>API workflow integrations</section>'
    items = [{**info, 'provider': key, 'status': 'Managed' if key == 'hermes' else 'Not connected', 'enabled': key == 'hermes', 'availability': {'available': key == 'hermes'},
              'managed': key == 'hermes'} for key, info in PROVIDERS.items()]
    page = browser.new_page(viewport={'width': width, 'height': 900})
    def route(request):
        if request.request.url.endswith('/connectors'):
            request.fulfill(content_type='application/json', body=json.dumps({'items': items, 'links': []}))
        elif '/static/' in request.request.url:
            file = ROOT / 'static' / request.request.url.split('/static/', 1)[1]
            request.fulfill(path=str(file))
        else:
            request.fulfill(content_type='text/html', body=html)
    page.route('**/*', route)
    try:
        page.goto('https://connectors.test/')
        page.locator('[data-agent-cards] .connector-card').first.wait_for()
        assert page.get_by_role('tab', name='Agents').get_attribute('aria-selected') == 'true'
        assert page.locator('[data-agent-cards] h2').first.inner_text() == 'Hermes'
        assert page.locator('[data-agent-cards] .connector-card').first.locator('button:disabled').count() == 3
        assert page.locator('[data-connector-cards] h2').all_text_contents() == ['GitHub', 'Jira Cloud']
        page.screenshot(path=str(tmp_path / f'agents-{width}.png'))
        page.get_by_role('tab', name='Agents').press('ArrowRight')
        assert page.get_by_role('tab', name='Connectors').get_attribute('aria-selected') == 'true'
        assert page.locator('#connector-integrations').is_visible()
        page.get_by_role('tab', name='Connectors').press('End')
        assert page.locator('#workflow-integrations').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        page.close()


def test_hermes_connector_controls_are_managed(fleet, authenticated_client):
    from test_integrations import post
    for operation in ('connect', 'toggle', 'disconnect'):
        assert post(authenticated_client, '/connectors/hermes/' + operation, {}).status_code == 409
    graph = authenticated_client.get('/agents/api/graph').json()
    connectors = [n for n in graph['nodes'] if n['kind'] == 'connector' and n.get('source') == 'hermes']
    assert len(connectors) == 1
    assert any(e['source'] == 'agent:butler' and e['target'] == connectors[0]['id'] for e in graph['edges'])
