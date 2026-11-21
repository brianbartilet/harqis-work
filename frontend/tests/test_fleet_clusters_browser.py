"""Dense Fleet disclosure and dragging through the shipped bundle."""
from urllib.parse import urlparse
import pytest
from frontend.tests.test_agent_fleet import fleet, bridge


@pytest.mark.parametrize('width', [1440, 390])
def test_dense_groups_and_parent_drag(authenticated_client, fleet, width, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.agents import ecosystem
    fleet.initialize()
    graph = ecosystem.graph('frontend-test-user')
    butler = next(n for n in graph['nodes'] if n['id'] == 'agent:butler')
    other = next(n for n in graph['nodes'] if n['kind'] == 'agent' and n['id'] != butler['id'])
    other_id = other['agent_id']
    graph['nodes'] = [butler, other]
    graph['edges'] = []
    for i in range(200):
        parent = 'butler' if i < 100 else other_id
        graph['nodes'].append({'id': f'config:{i}', 'kind': 'configuration', 'label': f'Configuration {i:03}',
                               'agent_ids': [parent], 'assigned_agent_id': parent, 'color': '#60a5fa',
                               'summary': 'Browser fixture', 'workspace_ids': [], 'entity': True})
        graph['edges'].append({'source': 'agent:' + parent, 'target': f'config:{i}', 'relation': 'uses', 'direction': 'none'})
    # The cross-link must never pull Research's child when Butler is dragged.
    graph['edges'].append({'source': 'config:0', 'target': 'config:100', 'relation': 'related', 'direction': 'none'})
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('''window.fleetText=[];const original=CanvasRenderingContext2D.prototype.fillText;
          CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...args){
            if(window.fleetText.length>3000)window.fleetText=[];
            window.fleetText.push({text,font:this.font});return original.call(this,text,x,y,...args);
          };''')
        def route(r):
            u = urlparse(r.request.url)
            if u.path == '/agents/api/graph':
                r.fulfill(json=graph)
                return
            response = authenticated_client.request(r.request.method, u.path + ('?' + u.query if u.query else ''),
                content=r.request.post_data_buffer, headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code, content_type=response.headers.get('content-type','text/html'), body=response.content)
        page.route('https://fleet.test/**', route)
        page.goto('https://fleet.test/agents')
        page.locator('.fleet-map[aria-busy=false]').wait_for()
        if width < 900:
            page.get_by_role('button', name='Close Agent work drawer', exact=True).click()
        page.locator('.fleet-cluster-browser summary').click()
        page.locator('.fleet-cluster-items button').first.click()
        items = page.locator('.fleet-cluster-items button')
        playwright.expect(items).to_have_count(12 if width < 600 else 24)
        page.get_by_role('button', name='Next', exact=True).click()
        assert 'Configuration 000' not in items.all_text_contents()
        page.get_by_role('button', name='Previous', exact=True).click()
        assert 'Configuration 000' in items.all_text_contents()
        page.get_by_role('textbox', name='Search group entities').fill('Configuration 099')
        playwright.expect(items).to_have_count(1)
        items.first.click()
        page.get_by_role('button', name='Close group', exact=True).click()
        # Collapse the browser so it cannot obscure graph drag targets.
        if page.locator('.fleet-cluster-browser').get_attribute('open') is not None:
            page.locator('.fleet-cluster-browser summary').click()
        page.get_by_role('button', name='Fit view', exact=True).click()
        page.wait_for_timeout(600)
        page.screenshot(path=str(tmp_path / f'fleet-clusters-{width}.png'), full_page=True)
        assert page.evaluate("window.fleetText.some(t=>t.text.includes('100'))")
        assert not page.evaluate("window.fleetText.some(t=>parseFloat(t.font.match(/([\\d.]+)px/)[1])>14)")
        saved = lambda: page.evaluate("JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user'))")
        if width < 600:
            page.locator('.fleet-cluster-browser summary').click()
            page.locator('.fleet-cluster-items button').last.click()
            playwright.expect(page.locator('.fleet-cluster-items button')).to_have_count(12)
            page.screenshot(path=str(tmp_path / 'fleet-clusters-parent-navigation.png'), full_page=True)
            parents = saved()['positions']
            assert abs(parents['agent:butler']['x'] - parents[other['id']]['x']) + abs(parents['agent:butler']['y'] - parents[other['id']]['y']) > 100
            page.set_viewport_size({'width': 1440, 'height': 1100})
            page.wait_for_timeout(200)
            assert saved()['positions']['agent:butler'] == parents['agent:butler']
            assert saved()['positions'][other['id']] == parents[other['id']]
        if width == 1440:
            before = saved()
            transform = page.locator('.fleet-map canvas').first.evaluate('(c)=>({x:c.__zoom.x,y:c.__zoom.y,k:c.__zoom.k})')
            box = page.locator('.fleet-map canvas').first.bounding_box()
            pos = before['positions']['agent:butler']
            x, y = box['x'] + pos['x'] * transform['k'] + transform['x'], box['y'] + pos['y'] * transform['k'] + transform['y']
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x+60, y+40, steps=8)
            page.mouse.up()
            page.wait_for_timeout(300)
            after = saved()
            assert after['positions'][other['id']] == before['positions'][other['id']]
            delta = after['positions']['agent:butler']['x'] - pos['x']
            assert delta * transform['k'] == pytest.approx(60, abs=2)
            assert after['positions']['config:99']['x'] - before['positions']['config:99']['x'] == pytest.approx(delta)
            page.locator('.fleet-layout-menu summary').click()
            page.get_by_role('button', name='Undo layout', exact=True).click()
            assert saved()['positions'] == before['positions']
        assert not errors
        browser.close()
