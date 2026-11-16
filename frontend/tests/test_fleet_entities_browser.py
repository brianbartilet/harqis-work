"""Entity selection survives search and identity merges require a preview."""
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import pytest
from test_control_focus_browser import browser

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def bundle(tmp_path_factory):
    target = tmp_path_factory.mktemp('entities-ui')/'entities.js'
    source = """import React from 'react';
import {createRoot} from 'react-dom/client';
import {FleetEntities} from './frontend/src/fleet-entities.jsx';
const items=[{id:'calendar',kind:'application',label:'Google Calendar',source:'nod',namespace:'nod:apps',state:'observed'},
{id:'photos',kind:'application',label:'Google Photos',source:'nod',namespace:'nod:apps',state:'observed'}];
window.edges=[];window.calls=[];
async function api(path,data){window.calls.push({path,data});if(path==='/entities/associate'){window.edges=data.linked?[...window.edges,{source:'agent:a',target:data.entity_id,relation:'linked'}]:window.edges.filter(e=>e.target!==data.entity_id);}return {items,edges:window.edges,merges:[]};}
createRoot(document.getElementById('app')).render(<main className="fleet-shell"><aside className="fleet-inspector"><FleetEntities agent={{id:'a',name:'Nod'}} api={api} refresh={async()=>{}}/></aside></main>);
"""
    script = 'require("esbuild").buildSync('+json.dumps({'stdin':{'contents':source,'resolveDir':str(ROOT),'loader':'jsx'},'bundle':True,'outfile':str(target),'format':'iife'})+')'
    subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)
    return target.read_text('utf-8')


@pytest.mark.parametrize('width',[390,1440])
def test_search_preserves_selection(browser,bundle,width,tmp_path):
    from playwright.sync_api import expect
    page=browser.new_page(viewport={'width':width,'height':900})
    try:
        page.set_content('<div id="app"></div>')
        page.add_style_tag(content='\n'.join((ROOT/'frontend/static/css'/f'{name}.css').read_text('utf-8') for name in ('app.min','agent-fleet')))
        page.add_script_tag(content=bundle)
        page.get_by_text('Connected entities',exact=True).click()
        page.get_by_role('checkbox').first.check()
        expect(page.get_by_text('1 manually linked',exact=True)).to_be_visible()
        page.get_by_label('Find entities').fill('Photos')
        expect(page.get_by_role('checkbox')).not_to_be_checked()
        page.get_by_role('checkbox').check()
        page.get_by_label('Find entities').fill('Calendar')
        expect(page.get_by_role('checkbox')).to_be_checked()
        page.get_by_role('checkbox').uncheck()
        expect(page.get_by_text('1 manually linked',exact=True)).to_be_visible()
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(tmp_path/f'entities-{width}.png'))
        page.get_by_text('Connected entities',exact=True).click()
        page.get_by_text('Connected entities',exact=True).click()
        page.get_by_label('Find entities').fill('Photos')
        expect(page.get_by_role('checkbox')).to_be_checked()
    finally:
        page.close()


@pytest.mark.parametrize('width',[390,1440])
def test_nod_entities_in_actual_fleet(browser,authenticated_client,monkeypatch,tmp_path,width):
    from playwright.sync_api import expect
    from modules.integrations.nod import link
    monkeypatch.setenv('HARQIS_NOD_MOCK','1')
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW','1')
    monkeypatch.setenv('HARQIS_CONNECTORS_DB',str(tmp_path/'connectors.sqlite3'))
    agent=link('frontend-test-user',{})['item']
    client=authenticated_client
    page=browser.new_page(viewport={'width':width,'height':900})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def route(r):
        u=urlparse(r.request.url)
        response=client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
            headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
        r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/html'))
    page.route('https://fleet.test/**',route)
    try:
        page.goto('https://fleet.test/agents?agent='+agent['id'])
        page.locator('.fleet-layout-loading').wait_for(state='hidden')
        if width < 900:
            page.get_by_role('button',name='Close Agent work drawer',exact=True).click()
        page.get_by_text('Connected entities',exact=True).click()
        expect(page.get_by_role('button',name='Refresh Nod entities',exact=True)).to_be_visible()
        expect(page.locator('.fleet-entity-option').get_by_text('Google Calendar',exact=True)).to_be_visible()
        page.get_by_role('button',name='Refresh Nod entities',exact=True).click()
        expect(page.get_by_role('button',name='Refresh Nod entities',exact=True)).to_be_enabled()
        graph=client.get('/agents/api/graph').json()
        assert any(n['kind']=='schedule' and n['label']=='Morning briefing' for n in graph['nodes'])
        assert len([n for n in graph['nodes'] if n['kind']=='application' and n['label']=='Google Calendar'])==1
        assert any(n['kind']=='connector' and n['source']=='nod' for n in graph['nodes'])
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.screenshot(path=str(tmp_path/f'nod-fleet-{width}.png'))
        page.goto('https://fleet.test/applications')
        logo=page.locator('.connector-card').filter(has=page.get_by_role('heading',name='Nod',exact=True)).locator('img')
        expect(logo).to_be_visible()
        assert logo.evaluate('e=>e.complete&&e.naturalWidth>0')
        page.screenshot(path=str(tmp_path/f'nod-connectors-{width}.png'))
        assert not errors
    finally:
        page.close()
