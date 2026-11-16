"""An uncertain send retains its request ID and draft on desktop and mobile."""
import json
from pathlib import Path
import subprocess
import pytest
from test_control_focus_browser import browser

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def nod_bundle(tmp_path_factory):
    target = tmp_path_factory.mktemp('nod-ui')/'nod.js'
    source = """import React from 'react';
import {createRoot} from 'react-dom/client';
import {NodConversation} from './frontend/src/nod-conversation.jsx';
window.sent=[];
const state={thread_id:'t',binding:'b',url:'https://nod.example.test',mock:true,active:true,ready:true,messages:[],turns:[],tasks:[]};
async function api(path,data){if(path.endsWith('/send')){window.sent.push(data);if(window.sent.length===1)throw Error('Response lost');return {messageId:data.request_id};}return state;}
createRoot(document.getElementById('app')).render(<main className="fleet-shell"><NodConversation agent={{id:'a',mock:true}} api={api} refresh={async()=>{}}/></main>);
"""
    script = "require('esbuild').buildSync(" + json.dumps({'stdin': {'contents': source, 'resolveDir': str(ROOT), 'loader':'jsx'}, 'bundle':True, 'outfile':str(target), 'format':'iife', 'define':{'process.env.NODE_ENV':'"production"'}}) + ')'
    subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)
    return target.read_text('utf-8')


@pytest.mark.parametrize('width',[390,1440])
def test_nod_uncertain_send_retains_request(browser,nod_bundle,width):
    from playwright.sync_api import expect
    page=browser.new_page(viewport={'width':width,'height':900})
    try:
        # localhost gives crypto.randomUUID a secure context without a running server.
        page.route('http://localhost/nod-test',lambda route:route.fulfill(body='<div id="app"></div>',content_type='text/html'))
        page.goto('http://localhost/nod-test')
        css='\n'.join((ROOT/'frontend/static/css'/f'{name}.css').read_text('utf-8') for name in ('app.min','agent-fleet'))
        page.add_style_tag(content=css)
        page.add_script_tag(content=nod_bundle)
        box=page.get_by_label('Message Nod',exact=True)
        box.fill('Keep this instruction')
        page.get_by_role('button',name='Send to Nod',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Response lost')
        expect(box).to_have_value('Keep this instruction')
        expect(box).to_have_attribute('readonly','')
        page.get_by_role('button',name='Retry retained request').click()
        expect(box).to_have_value('')
        calls=page.evaluate('window.sent')
        assert len(calls)==2 and calls[0]==calls[1]
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    finally:
        page.close()
