"""Drawer switching preserves controls and keeps the graph usable at small widths."""
import json
from pathlib import Path
import subprocess

import pytest
from test_control_focus_browser import browser

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def drawer_bundle(tmp_path_factory):
    target = tmp_path_factory.mktemp('fleet-drawers') / 'drawers.js'
    source = '''import React from 'react';
import {createRoot} from 'react-dom/client';
import {FleetDrawers} from './frontend/src/fleet-drawers.jsx';
function Hud(){return <div className="fleet-hud-panel" data-expanded="false"><input aria-label="HUD setting" defaultValue=""/></div>;}
createRoot(document.getElementById('app')).render(<div className="fleet-shell" style={{height:850}}>
 <div className="fleet-workspace fleet-has-drawers">
  <FleetDrawers work={<input aria-label="Work filter" defaultValue=""/>}
   hud={<Hud/>}/>
  <div className="fleet-map">Graph</div><aside className="fleet-inspector">Inspector</aside>
 </div></div>);'''
    script = "require('esbuild').buildSync(" + json.dumps(dict(
        stdin=dict(contents=source, resolveDir=str(ROOT), loader='jsx'),
        bundle=True, outfile=str(target), format='iife',
        define={'process.env.NODE_ENV': '"production"'},
    )) + ')'
    subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True)
    return target.read_text(encoding='utf-8')


@pytest.mark.parametrize('width', [390, 1440])
def test_drawer_switch_close_and_keyboard_focus(browser, drawer_bundle, width):
    page = browser.new_page(viewport={'width': width, 'height': 900})
    page.set_default_timeout(5000)
    try:
        css = '\n'.join((ROOT / 'frontend/static/css' / f'{name}.css').read_text(encoding='utf-8')
                        for name in ('app.min', 'agent-fleet', 'control-focus'))
        page.set_content('<style>body{margin:0}</style><style>'+css+'</style><div id="app"></div>')
        page.add_script_tag(content=drawer_bundle)
        work = page.get_by_role('button', name='Agent work', exact=True)
        hud = page.get_by_role('button', name='HUD', exact=True)
        work.dblclick()
        assert page.locator('#fleet-work-drawer').is_visible()
        page.get_by_label('Work filter').fill('Keep my filter')
        hud.click()
        assert page.locator('#fleet-work-drawer').is_hidden()
        assert hud.get_attribute('aria-expanded') == 'true'
        hud.dblclick()
        assert page.locator('#fleet-hud-drawer').is_visible()
        page.get_by_label('HUD setting').fill('Keep my setting')
        work.click()
        assert page.get_by_label('Work filter').input_value() == 'Keep my filter'
        assert page.locator('#fleet-hud-drawer').is_hidden()
        hud.click()
        assert page.get_by_label('HUD setting').input_value() == 'Keep my setting'
        page.get_by_label('HUD setting').press('Escape')
        assert page.locator('#fleet-hud-drawer').is_hidden()
        assert hud.evaluate('e=>e===document.activeElement')
        hud.press('Enter')
        assert page.locator('#fleet-hud-drawer').is_visible()
        nav = page.get_by_role('navigation', name='Workspace drawers')
        nav_bounds = nav.bounding_box()
        assert nav_bounds['width'] < 120
        assert nav_bounds['x'] >= 0 and nav_bounds['x'] + nav_bounds['width'] <= width
        assert nav_bounds['y'] > 400
        bounds = page.locator('#fleet-hud-drawer').bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
        hud.press('Escape')
        assert hud.get_attribute('aria-expanded') == 'false'
        assert nav.is_visible()
        hud.click()
        assert page.locator('#fleet-hud-drawer').is_visible()
        hud.press('Escape')
        assert hud.evaluate('e=>e===document.activeElement')
    finally:
        page.close()


@pytest.mark.parametrize('width', [390, 1440])
def test_hud_entity_view_opens_drawer_and_focuses_card(browser, tmp_path, width):
    source = """import React,{useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {FleetDrawers} from './frontend/src/fleet-drawers.jsx';
import {AgentHud} from './frontend/src/fleet-hud.jsx';
function App(){
 const [open,setOpen]=useState('work'),hud=useRef();
 const agent={id:'a',name:'Agent A',workflows:[],triggers:[]};
 const nodes=[{id:'hud:calendar',kind:'hud',label:'Calendar',agent_ids:['a']}];
 return <div className="fleet-shell" style={{height:850}}><div className="fleet-workspace fleet-has-drawers">
  <FleetDrawers open={open} onOpenChange={setOpen} work={<p>Agent work</p>}
   hud={<AgentHud ref={hud} agent={agent} agents={[agent]} nodes={nodes} owner="test"/>}/>
  <div className="fleet-map"/><aside className="fleet-inspector"><button onClick={()=>{
   setOpen('hud');requestAnimationFrame(()=>hud.current.reveal('hud:calendar'));
  }}>View</button></aside>
 </div></div>;
}
createRoot(document.getElementById('app')).render(<App/>);"""
    target = tmp_path / 'hud-navigation.js'
    script = "require('esbuild').buildSync(" + json.dumps(dict(
        stdin=dict(contents=source, resolveDir=str(ROOT), loader='jsx'),
        bundle=True, outfile=str(target), format='iife',
        define={'process.env.NODE_ENV': '"production"'},
    )) + ')'
    subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True)
    page = browser.new_page(viewport={'width': width, 'height': 900})
    page.set_default_timeout(5000)
    try:
        page.on('pageerror', lambda error: print('HUD page error:', error))
        layout = {'widgets': [{'operation': 'calendar', 'size': '3x1'}]}
        def layout_request(route):
            if route.request.method == 'PUT':
                layout.update(route.request.post_data_json)
            route.fulfill(json=layout)
        page.route('**/agents/hud/layout', layout_request)
        page.route('**/agents/hud/data', lambda route: route.fulfill(json={
            'layout': layout,
            'items': {}, 'agents': {'calendar': []},
        }))
        page.route('http://localhost:9876/', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.goto('http://localhost:9876/')
        css = '\n'.join((ROOT / 'frontend/static/css' / f'{name}.css').read_text(encoding='utf-8')
                        for name in ('app.min', 'agent-fleet', 'control-focus'))
        page.set_content('<style>'+css+'</style><script id="fleet-csrf" type="application/json">"test"</script><div id="app"></div>')
        page.add_script_tag(content=target.read_text(encoding='utf-8'))
        page.wait_for_function("document.querySelector('.hud-placeholder')?.textContent==='Waiting for the first capture.'")
        # A selected entity has an inspector on mobile too.
        page.locator('.fleet-workspace').evaluate("el=>el.classList.add('fleet-has-selection')")
        if width < 900:
            page.get_by_role('button', name='Agent work', exact=True).press('Escape')
        page.get_by_role('button', name='View', exact=True).click()
        assert page.locator('#fleet-work-drawer').is_hidden()
        assert page.locator('#fleet-hud-drawer').is_visible()
        assert page.locator('[data-id="hud:calendar"]').evaluate('el=>el===document.activeElement')
        grid = page.locator('.fleet-hud-grid')
        assert grid.evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length") == 2
        page.get_by_role('button', name='Expand HUD panel').click()
        page.wait_for_function("document.querySelector('.fleet-hud-panel').dataset.expanded==='true'")
        assert grid.evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length") == 3
        assert page.locator('.fleet-hud-panel').evaluate('el=>el.scrollWidth===el.clientWidth')
        page.get_by_role('button', name='Agent work', exact=True).click()
        assert abs(page.locator('#fleet-work-drawer').bounding_box()['width'] - 339) < 2
        page.get_by_role('button', name='HUD', exact=True).click()
        card = page.locator('[data-id="hud:calendar"]')
        assert abs(card.bounding_box()['width'] - grid.bounding_box()['width']) < 1
        page.screenshot(path=str(tmp_path / f'hud-grid-{width}.png'))
        page.get_by_role('button', name='HUD', exact=True).press('Escape')
        assert page.locator('#fleet-hud-drawer').is_hidden()
        assert page.get_by_role('button', name='HUD', exact=True).evaluate('el=>el===document.activeElement')
    finally:
        page.close()
