"""Fleet Action controls retain the current page and apply versioned status changes."""
import json
import subprocess
from pathlib import Path

import pytest
from test_control_focus_browser import browser

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('width', [390, 1440])
def test_fleet_action_controls(browser, tmp_path, width):
    bundle = tmp_path / 'work.js'
    source = '''import React from 'react';
import {createRoot} from 'react-dom/client';
import {AgentWork} from './frontend/src/fleet-work.jsx';
window.HflIdeas={openAction:id=>window.openedAction=id};
const agents=[{id:'a',name:'Research',runtime:'hermes',color:'#facc15'}];
const nodes=[{id:'action:one',record_id:'one',kind:'action',label:'Research task',agent_ids:['a'],record:{status:'active'},url:'/hfl-corpus/actions?edit=one'}];
createRoot(document.getElementById('app')).render(<AgentWork nodes={nodes} agents={agents} agentId="" setAgentId={()=>{}} Avatar={()=>null} loaded ask={()=>{}} scope="All activity"/>);
'''
    subprocess.run(['node', '-e', 'require("esbuild").buildSync(' + json.dumps({
        'stdin': {'contents': source, 'resolveDir': str(ROOT), 'loader': 'jsx'},
        'bundle': True, 'outfile': str(bundle), 'format': 'iife',
        'define': {'process.env.NODE_ENV': '"production"'},
    }) + ')'], cwd=ROOT, check=True, capture_output=True)
    page = browser.new_page(viewport={'width': width, 'height': 900})
    patches = []
    def route(request):
        if request.request.method == 'PATCH':
            payload = request.request.post_data_json
            patches.append(payload)
            request.fulfill(json={'item': {'id': 'one', 'version': 8, 'status': payload['status']}})
        else:
            request.fulfill(json={'item': {'id': 'one', 'version': 7, 'status': 'active'}})
    try:
        page.route('http://fleet.test/', lambda r: r.fulfill(body='<div id="app"></div>'))
        page.route('**/hfl-corpus/timeline/items/one', route)
        page.goto('http://fleet.test/')
        for name in ('agent-fleet', 'hfl-timeline'):
            page.add_style_tag(path=str(ROOT / 'frontend/static/css' / (name + '.css')))
        page.add_script_tag(path=str(bundle))
        from playwright.sync_api import expect
        expect(page.get_by_role('button', name='Ready', exact=True)).to_have_count(0)
        page.get_by_role('button', name='Open', exact=True).click()
        assert page.evaluate('window.openedAction') == 'one'
        page.get_by_role('link', name='Research task').click()
        assert page.url == 'http://fleet.test/'
        assert page.locator('.action-agent-type').evaluate("e=>e.style.getPropertyValue('--agent-type-color')") == '#facc15'
        page.get_by_role('button', name='Done', exact=True).click()
        expect(page.get_by_role('button', name='Done', exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='Ready', exact=True)).to_be_visible()
        assert patches == [{'version': 7, 'status': 'done'}]
        page.screenshot(path=str(tmp_path / f'fleet-work-{width}.png'))
    finally:
        page.close()
