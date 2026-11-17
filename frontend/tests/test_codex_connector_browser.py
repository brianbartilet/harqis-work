"""Codex onboarding reuses the fleet connection controls at both viewport sizes."""
import json
import subprocess
from pathlib import Path
import pytest
from test_control_focus_browser import browser
from test_codex_connector import host
from test_agent_fleet import fleet
from test_hfl_agent_bridge import bridge

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('width', [390, 1440])
def test_codex_setup_instructions(browser, tmp_path, width):
    from playwright.sync_api import expect
    page = browser.new_page(viewport={'width': width, 'height': 900})
    try:
        page.route('**/integrations/api/connectors', lambda route: route.fulfill(
            json={'items': [{'provider': 'codex', 'name': 'Codex', 'status': 'Not connected', 'enabled': False, 'capabilities': ['Tasks', 'Plugins']}], 'links': []}))
        page.route('https://harqis.test/', lambda route: route.fulfill(
            content_type='text/html', body='<div data-connector-cards></div><p data-integration-error></p>'))
        page.goto('https://harqis.test/')
        page.add_style_tag(content=(ROOT/'frontend/static/css/integrations.css').read_text('utf-8'))
        page.add_script_tag(content=(ROOT/'frontend/static/js/integrations.js').read_text('utf-8'))
        page.get_by_role('button', name='Connect', exact=True).click()
        dialog = page.get_by_role('dialog', name='Connect Codex')
        help_button = dialog.get_by_role('button', name='Host setup instructions')
        expect(help_button).to_have_attribute('aria-expanded', 'false')
        help_button.click()
        expect(help_button).to_have_attribute('aria-expanded', 'true')
        expect(dialog.get_by_text('python scripts/setup_codex.py --remote <machine-key>', exact=True)).to_be_visible()
        expect(dialog.locator('pre')).to_contain_text('HARQIS_CODEX_BINARY')
        expect(dialog.get_by_text('python scripts/deploy.py --restart frontend', exact=True)).to_be_visible()
        expect(dialog.get_by_role('button', name='Save and enable')).to_be_disabled()
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(tmp_path/f'codex-setup-{width}.png'))
        help_button.click()
        expect(help_button).to_have_attribute('aria-expanded', 'false')
        page.route('**/integrations/api/connectors/codex/test', lambda route: route.fulfill(
            status=503, json={'detail': 'Codex executable unavailable'}))
        dialog.get_by_role('button', name='Test local host').click()
        expect(help_button).to_have_attribute('aria-expanded', 'true')
        expect(dialog.get_by_role('alert')).to_have_text('Codex executable unavailable')
    finally:
        page.close()


@pytest.fixture(scope='module')
def codex_bundle(tmp_path_factory):
    output = tmp_path_factory.mktemp('codex-ui')/'test.js'
    source = """import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {CodexConnection} from './frontend/src/codex-connection.jsx';
window.calls=[];window.fail=false;
async function api(path,data){window.calls.push({path,data});if(window.fail)throw Error('Host unavailable');if(path==='/connectors')return {items:[{provider:'codex',enabled:true,account:'Local host'}]};return {counts:{tasks:2,applications:3},warnings:[]};}
function Demo(){const [selected,setSelected]=useState(true);return <main className="fleet-shell"><div className="fleet-form"><CodexConnection selected={selected} onChange={setSelected} api={api} refreshed={async()=>{}}/><CodexConnection agent={{id:'ada',connector_provider:'codex'}} api={api} refreshed={async()=>{}}/></div></main>;}
createRoot(document.getElementById('app')).render(<Demo/>);
"""
    settings = {'stdin': {'contents': source, 'resolveDir': str(ROOT), 'loader': 'jsx'}, 'bundle': True, 'outfile': str(output)}
    subprocess.run(['node', '-e', 'require("esbuild").buildSync('+json.dumps(settings)+')'], cwd=ROOT, check=True, capture_output=True)
    return output.read_text('utf-8')


@pytest.mark.parametrize('width', [390, 1440])
def test_codex_connection(browser, codex_bundle, tmp_path, width):
    from playwright.sync_api import expect
    page = browser.new_page(viewport={'width': width, 'height': 900})
    try:
        page.set_content('<div id="app"></div>')
        page.add_style_tag(content='\n'.join((ROOT/'frontend/static/css'/f'{name}.css').read_text('utf-8') for name in ('app.min', 'agent-fleet')))
        page.add_script_tag(content=codex_bundle)
        check = page.get_by_role('checkbox', name='Link the existing Codex installation')
        expect(check).to_be_checked()
        check.uncheck()
        expect(page.get_by_text('Save a manual profile without discovery.', exact=False)).to_be_visible()
        page.get_by_role('button', name='Refresh observations').click()
        expect(page.get_by_role('status')).to_contain_text('2 tasks · 3 applications')
        page.evaluate('window.fail=true')
        page.get_by_role('button', name='Refresh observations').click()
        expect(page.get_by_role('alert')).to_have_text('Host unavailable')
        expect(check).not_to_be_checked()
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(tmp_path/f'codex-{width}.png'))
    finally:
        page.close()


@pytest.mark.parametrize('width', [390, 1440])
def test_actual_fleet_codex_editor(browser, host, fleet, authenticated_client, tmp_path, width):
    from urllib.parse import urlparse
    from playwright.sync_api import expect
    from test_hfl_agent_bridge import owner_headers
    client = authenticated_client
    headers = owner_headers()
    assert client.post('/integrations/api/connectors/codex/save', json={}, headers=headers).status_code == 200
    assert client.post('/integrations/api/connectors/codex/toggle', json={'enabled': True}, headers=headers).status_code == 200
    page = browser.new_page(viewport={'width': width, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    def route(r):
        u = urlparse(r.request.url)
        response = client.request(r.request.method, u.path+('?' + u.query if u.query else ''), content=r.request.post_data_buffer,
            headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
        r.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get('content-type','text/html'))
    page.route('https://codex.test/**', route)
    try:
        page.goto('https://codex.test/applications')
        codex_card = page.locator('.connector-card').filter(has=page.get_by_role('heading', name='Codex', exact=True))
        expect(codex_card).to_be_visible()
        expect(codex_card.get_by_role('status')).to_have_text('Connected')
        expect(page.get_by_role('heading', name='Grok Bot', exact=True)).to_be_visible()
        expect(page.locator('[data-integration-error]')).to_be_empty()
        page.screenshot(path=str(tmp_path/f'codex-connected-{width}.png'))
        page.goto('https://codex.test/agents')
        page.wait_for_function('Array.from(document.querySelectorAll("img")).some(img => img.src.includes("img/connectors/codex.svg") && img.naturalWidth > 0)')
        page.screenshot(path=str(tmp_path/f'codex-fleet-logo-{width}.png'))
        page.get_by_role('button', name='Add agent', exact=True).click()
        page.get_by_label('Name', exact=True).fill('New Codex label')
        page.get_by_label('Agent service').select_option('codex')
        expect(page.get_by_role('checkbox', name='Link the existing Codex installation')).to_be_checked()
        expect(page.get_by_text('Connected · Codex', exact=False)).to_be_visible()
        page.get_by_role('checkbox', name='Link the existing Codex installation').scroll_into_view_if_needed()
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(tmp_path/f'codex-editor-{width}.png'))
        page.get_by_role('button', name='Save agent', exact=True).click()
        expect(page.get_by_role('button', name='Save agent', exact=True)).not_to_be_visible()
        profiles = client.get('/agents/api/items').json()['items']
        assert len([p for p in profiles if p.get('connector_provider') == 'codex']) == 1
        assert not errors
    finally:
        page.close()
