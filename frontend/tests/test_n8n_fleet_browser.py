"""n8n draft conflict and capture controls work at desktop and mobile widths."""
import json
from pathlib import Path
import subprocess
import pytest
from test_control_focus_browser import browser

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def n8n_bundle(tmp_path_factory):
    target = tmp_path_factory.mktemp('n8n-fleet') / 'n8n.js'
    source = """import React from 'react';
import {createRoot} from 'react-dom/client';
import {N8nDetails,N8nPicker} from './frontend/src/fleet-n8n.jsx';
const agent={id:'a',remote_id:'remote',version:1,mock:true,n8n_snapshot:{name:'Atlas',instructions:'Review workflows',config_hash:'hash',synced_at:'2026-11-16T00:00:00Z',published:true,runnable:true,can_edit:true,warnings:[],workflows:[],schedules:[],executions:[{id:'1',workflow_name:'Briefing',status:'success'}]}};
async function api(path,data){
 if(path.includes('/draft'))throw Error('n8n changed since your last refresh. Refresh and review before saving.');
 if(path.includes('/capture'))return {preview:true};
 return {items:[{id:'remote',name:'Atlas',availableInMCP:true}]};
}
function App(){const [choice,setChoice]=React.useState(null);return <main className="fleet-shell"><N8nPicker api={api} value={choice} onChange={setChoice}/><N8nDetails agent={agent} api={api} refresh={async()=>{}}/></main>}
createRoot(document.getElementById('app')).render(<App/>);"""
    script = "require('esbuild').buildSync(" + json.dumps({'stdin': {'contents':source,'resolveDir':str(ROOT),'loader':'jsx'}, 'bundle':True,'outfile':str(target),'format':'iife','define':{'process.env.NODE_ENV':'"production"'}}) + ')'
    subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)
    return target.read_text('utf-8')


@pytest.mark.parametrize('width',[390,1440])
def test_n8n_picker_conflict_retains_draft_and_capture(browser,n8n_bundle,width):
    from playwright.sync_api import expect
    page=browser.new_page(viewport={'width':width,'height':900})
    try:
        css='\n'.join((ROOT/'frontend/static/css'/f'{name}.css').read_text('utf-8') for name in ('app.min','agent-fleet','control-focus'))
        page.set_content('<style>'+css+'</style><div id="app"></div>')
        page.add_script_tag(content=n8n_bundle)
        expect(page.get_by_label('n8n agent',exact=True).locator('option')).to_have_count(2)
        page.get_by_label('n8n agent',exact=True).select_option('remote')
        page.get_by_role('button',name='Edit n8n draft',exact=True).click()
        page.get_by_label('n8n draft name',exact=True).fill('My unsaved edit')
        page.get_by_role('button',name='Save draft to n8n',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('n8n changed')
        assert page.get_by_label('n8n draft name',exact=True).input_value()=='My unsaved edit'
        page.get_by_role('button',name='Cancel',exact=True).click()
        page.get_by_role('button',name='Capture executions in corpus',exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('production corpus untouched')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        page.close()
