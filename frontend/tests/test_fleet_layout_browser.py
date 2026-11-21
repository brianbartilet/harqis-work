"""Saved Fleet views preserve fixed entities and readable dense labels."""
import json
import math
from urllib.parse import urlparse

import pytest
from frontend.tests.test_agent_fleet import fleet, bridge


@pytest.mark.parametrize('width', [1440, 390])
def test_save_reset_and_fixed_entities(authenticated_client, fleet, width, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.agents import ecosystem
    fleet.initialize()
    graph = ecosystem.graph('frontend-test-user')
    parent = next(n for n in graph['nodes'] if n['id'] == 'agent:butler')
    graph['nodes'] = [parent]
    graph['edges'] = []
    scale = .0001
    positions = {'agent:butler': {'x': 0, 'y': 0, 'manual': True}}
    for i in range(60):
        identity = f'config:{i}'
        graph['nodes'].append({'id': identity, 'kind': 'configuration', 'label': f'Configuration {i:02}',
                               'agent_ids': ['butler'], 'assigned_agent_id': 'butler',
                               'color': '#60a5fa', 'workspace_ids': [], 'entity': True})
        graph['edges'].append({'source': 'agent:butler', 'target': identity, 'relation': 'uses', 'direction': 'none'})
        angle = i * math.pi / 30
        radius = 90 + (i % 3) * 30
        positions[identity] = {'x': radius * math.cos(angle) / scale, 'y': radius * math.sin(angle) / scale,
                               'manual': i == 0, 'pinned': i == 1}
    initial = {'positions': positions, 'viewport': {'x': 0, 'y': 0, 'zoom': scale}, 'animation': 'off'}
    key = 'harqis:fleet:graph:v2:frontend-test-user'
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1100})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script(f"if(!localStorage.getItem('{key}'))localStorage.setItem('{key}',{json.dumps(json.dumps(initial))});")
        page.add_init_script("""window.labelFonts=[];
          const original=CanvasRenderingContext2D.prototype.fillText;
          CanvasRenderingContext2D.prototype.fillText=function(text,...args){
            if(window.labelFonts.length<10000)window.labelFonts.push({text,font:this.font});
            return original.call(this,text,...args);
          };""")

        def route(r):
            u = urlparse(r.request.url)
            if u.path == '/agents/api/graph':
                r.fulfill(json=graph)
                return
            response = authenticated_client.request(r.request.method, u.path + ('?' + u.query if u.query else ''),
                content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code, content_type=response.headers.get('content-type','text/html'), body=response.content)

        page.route('https://fleet.test/**', route)
        page.goto('https://fleet.test/agents')
        page.locator('.fleet-map[aria-busy=false]').wait_for()
        if width < 900:
            page.get_by_role('button', name='Close Agent work drawer', exact=True).click()
        page.wait_for_function("window.labelFonts.some(p=>p.text.startsWith('Configuration'))")
        assert page.evaluate("window.labelFonts.every(p=>parseFloat(p.font.match(/([\\d.]+)px/)[1])<=14)")
        assert '?v=' in page.locator('script[src*="agent-fleet.js"]').get_attribute('src')
        saved = lambda: page.evaluate(f"JSON.parse(localStorage.getItem('{key}'))")
        before = saved()

        # Drag the parent: both kinds of fixed child must retain their flag and position.
        canvas = page.locator('.fleet-map canvas').first
        transform = canvas.evaluate('(c)=>({x:c.__zoom.x,y:c.__zoom.y,k:c.__zoom.k})')
        box = canvas.bounding_box()
        x, y = box['x'] + transform['x'], box['y'] + transform['y']
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 35, y + 20, steps=8)
        page.mouse.up()
        page.get_by_role('button', name='Reset positions', exact=True).click()
        page.wait_for_timeout(1700)
        after = saved()
        for identity in ['config:0', 'config:1']:
            assert after['positions'][identity] == before['positions'][identity]
        assert after['positions']['agent:butler']['x'] * scale == pytest.approx(35, abs=2)
        assert after['viewport'] == before['viewport']

        page.get_by_role('button', name='Save layout', exact=True).click()
        playwright.expect(page.get_by_role('status').filter(has_text='Layout saved in this browser.')).to_be_visible()
        snapshot = saved()
        assert snapshot['layoutSavedAt'] > 0
        assert len(snapshot['positions']) == 61
        page.screenshot(path=str(tmp_path / f'fleet-layout-{width}.png'), full_page=True)
        save_box = page.get_by_role('button', name='Save layout', exact=True).bounding_box()
        assert 0 <= save_box['x'] and save_box['x'] + save_box['width'] <= width
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

        page.reload()
        page.locator('.fleet-map[aria-busy=false]').wait_for()
        assert saved()['positions'] == snapshot['positions']
        assert saved()['viewport'] == snapshot['viewport']
        if width < 900 and page.get_by_role('button', name='Close Agent work drawer', exact=True).is_visible():
            page.get_by_role('button', name='Close Agent work drawer', exact=True).click()
        page.evaluate("""() => {const original=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){
            if(key==='harqis:fleet:graph:v2:frontend-test-user')throw new DOMException('Full','QuotaExceededError');
            return original.call(this,key,value);
          };
        }""")
        page.get_by_role('button', name='Save layout', exact=True).click()
        playwright.expect(page.get_by_role('status').filter(has_text='Could not save layout.')).to_be_visible()
        assert not errors
        browser.close()
