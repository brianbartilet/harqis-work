"""Fleet zoom controls apply every click without competing camera transitions."""
from urllib.parse import urlparse
import pytest
from frontend.tests.test_agent_fleet import fleet, bridge


@pytest.mark.parametrize('width', [1440,390])
def test_repeated_zoom_out_and_wheel(authenticated_client, fleet, width):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.agents import ecosystem
    fleet.initialize()
    graph = ecosystem.graph('frontend-test-user')
    graph['nodes'] = [n for n in graph['nodes'] if n['id'] in {'agent:butler', 'hud:context', 'owner:corpus'}]
    ids = {n['id'] for n in graph['nodes']}
    graph['edges'] = [e for e in graph['edges'] if e['source'] in ids and e['target'] in ids]
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width':width,'height':1000})
        page.add_init_script("if(!localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user'))localStorage.setItem('harqis:fleet:graph:v2:frontend-test-user',JSON.stringify({viewport:{x:0,y:0,zoom:1},positions:{'agent:butler':{x:0,y:40},'owner:corpus':{x:-85,y:-45},'hud:context':{x:85,y:-45}}}));")
        def route(r):
            u = urlparse(r.request.url)
            if u.path == '/agents/api/graph':
                r.fulfill(json=graph); return
            response = authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://fleet.test/**',route)
        page.goto('https://fleet.test/agents')
        page.locator('.fleet-map[aria-busy=false]').wait_for()
        if width < 900:
            page.get_by_role('button',name='Close Agent work drawer',exact=True).click()
        zoom = lambda: page.locator('.fleet-map canvas').first.evaluate('(el)=>el.__zoom.k')
        before = zoom()
        for _ in range(3):
            page.get_by_role('button',name='Zoom out',exact=True).click()
        page.wait_for_timeout(1200)
        after = zoom()
        print('Zoom before/after three clicks:',before,after)
        assert after == pytest.approx(before/1.3**3,rel=.03)
        for _ in range(3):
            page.get_by_role('button',name='Zoom in',exact=True).click()
        assert zoom() == pytest.approx(before,rel=.03)
        after=zoom()
        box=page.locator('.fleet-map canvas').first.bounding_box()
        page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
        page.mouse.wheel(0,300)
        page.wait_for_timeout(500)
        assert zoom()<after
        saved = lambda: page.evaluate("JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user'))")
        prior=saved()
        page.get_by_role('button',name='Reset positions',exact=True).click()
        page.wait_for_timeout(1800)
        reset=saved()
        for identity in ['agent:butler','owner:corpus']:
            assert reset['positions'][identity] == prior['positions'][identity]
        assert reset['viewport'] == prior['viewport']
        assert reset['positions']['hud:context'] != prior['positions']['hud:context']
        # Zoom and animation must not change Reset's saved resting layout.
        for mode in ['Drift','Breathing','Ripple','Off']:
            page.get_by_role('button',name='Animation',exact=True).click()
            page.get_by_role('button',name=mode,exact=True).click()
            page.get_by_role('button',name='Zoom out',exact=True).click()
            page.get_by_role('button',name='Reset positions',exact=True).click()
            page.wait_for_timeout(2200)
            assert saved()['positions'] == reset['positions']
        reset=saved()
        page.reload()
        page.locator('.fleet-map[aria-busy=false]').wait_for()
        assert zoom() == pytest.approx(reset['viewport']['zoom'],rel=.01)
        assert saved()['positions']['hud:context']['x'] == pytest.approx(reset['positions']['hud:context']['x'])
        browser.close()
