"""Fleet provider links retain navigation and isolate popup windows."""
import json
from pathlib import Path
import subprocess

import pytest
from test_control_focus_browser import browser

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def interface_bundle(tmp_path_factory):
    target = tmp_path_factory.mktemp('interface-ui') / 'link.js'
    source = """import React from 'react';
import {createRoot} from 'react-dom/client';
import {OpenAgentInterface} from './frontend/src/fleet-interface-link.jsx';
createRoot(document.getElementById('app')).render(<main className="fleet-shell"><aside className="fleet-inspector"><div className="fleet-agent-toolbar">
<OpenAgentInterface provider="n8n" url="http://n8n.example.test:5678/projects/project/agents/agent" iconOnly/>
<OpenAgentInterface provider="Invalid" url="javascript:alert(1)"/>
<OpenAgentInterface provider="Credentials" url="https://user:secret@example.test"/>
</div></aside></main>);"""
    config = {'stdin': {'contents': source, 'resolveDir': str(ROOT), 'loader': 'jsx'},
              'bundle': True, 'outfile': str(target), 'format': 'iife',
              'define': {'process.env.NODE_ENV': '"production"'}}
    subprocess.run(['node', '-e', 'require("esbuild").buildSync(' + json.dumps(config) + ')'],
                   cwd=ROOT, check=True, capture_output=True)
    return target.read_text('utf-8')


@pytest.mark.parametrize('width', [390, 1440])
def test_n8n_interface_popup(browser, interface_bundle, width):
    page = browser.new_page(viewport={'width': width, 'height': 900})
    try:
        page.set_content('<div id="app"></div>')
        page.add_style_tag(content=(ROOT / 'frontend/static/css/agent-fleet.css').read_text('utf-8'))
        page.add_script_tag(content=interface_bundle)
        link = page.get_by_role('link', name='Open n8n in new window')
        assert link.get_attribute('href') == 'http://n8n.example.test:5678/projects/project/agents/agent'
        assert page.get_by_role('link').count() == 1
        page.context.route('http://n8n.example.test:5678/**', lambda route: route.fulfill(body='n8n'))
        with page.expect_popup() as opened:
            link.click()
        popup = opened.value
        popup.wait_for_load_state()
        assert popup.url.endswith('/projects/project/agents/agent')
        assert popup.evaluate('window.opener === null')
        popup.close()
        # A blocked popup must leave the anchor's ordinary navigation available.
        page.evaluate("window.open=()=>null;window.fallback=null;document.addEventListener('click',e=>{window.fallback=!e.defaultPrevented;e.preventDefault();});")
        link.click()
        assert page.evaluate('window.fallback')
    finally:
        page.close()
