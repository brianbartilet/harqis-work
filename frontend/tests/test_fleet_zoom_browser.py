"""Fleet zoom controls apply every click without competing camera transitions."""
from urllib.parse import urlparse
import pytest
from frontend.tests.test_agent_fleet import fleet, bridge


@pytest.mark.parametrize('width', [1440,390])
@pytest.mark.parametrize('retired_layout', [False,True])
def test_repeated_zoom_out_and_wheel(authenticated_client, fleet, width, retired_layout, tmp_path):
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
        if retired_layout:
            page.add_init_script("""const k='harqis:fleet:graph:v2:frontend-test-user';
              if(!localStorage.getItem(k+':retired-layout-v3')){
                const v=JSON.parse(localStorage.getItem(k));
                v.layoutVersion=3;v.expandedGroup='fleet-group:old';v.groupPage=3;
                v.positions['fleet-group:old']={x:0,y:0};v.inactive=true;
                localStorage.setItem(k,JSON.stringify(v));
              }""")
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
        if retired_layout:
            assert saved()['inactive'] is True
            assert 'layoutVersion' not in saved()
            assert 'expandedGroup' not in saved()
            assert 'groupPage' not in saved()
            assert not any(key.startswith('fleet-group:') for key in saved()['positions'])
            assert page.evaluate("!!localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user:retired-layout-v3')")
        assert page.locator('.fleet-cluster-browser, .fleet-layout-menu').count() == 0
        page.screenshot(path=str(tmp_path / f'fleet-restored-{width}.png'), full_page=True)
        prior=saved()
        page.get_by_role('button',name='Reset positions',exact=True).click()
        page.wait_for_timeout(1800)
        reset=saved()
        for identity in ['agent:butler','owner:corpus']:
            assert reset['positions'][identity] == prior['positions'][identity]
        assert reset['viewport'] == pytest.approx(prior['viewport'])
        assert reset['positions']['hud:context'] != prior['positions']['hud:context']
        # Reset keeps fixed anchors and the current camera across animation modes.
        for mode in ['Drift','Breathing','Ripple','Off']:
            page.get_by_role('button',name='Animation',exact=True).click()
            page.get_by_role('button',name=mode,exact=True).click()
            page.get_by_role('button',name='Zoom out',exact=True).click()
            camera = saved()['viewport']
            page.get_by_role('button',name='Reset positions',exact=True).click()
            page.wait_for_timeout(2200)
            for identity in ['agent:butler','owner:corpus']:
                assert saved()['positions'][identity] == reset['positions'][identity]
            assert saved()['viewport'] == pytest.approx(camera,abs=1e-8)
            assert saved()['animation'] == 'off'
        reset=saved()
        # Recover from layouts/cameras beyond the old 0.01 zoom floor.
        for _ in range(32):
            page.get_by_role('button',name='Zoom out',exact=True).click()
        assert zoom()<.01
        camera = saved()['viewport']
        page.get_by_role('button',name='Reset positions',exact=True).click()
        page.wait_for_timeout(1800)
        assert saved()['viewport'] == pytest.approx(camera,abs=1e-8)
        page.get_by_role('button',name='Fit view',exact=True).click()
        page.wait_for_timeout(300)
        reset=saved()
        transform=page.locator('.fleet-map canvas').first.evaluate('(el)=>({x:el.__zoom.x,y:el.__zoom.y,k:el.__zoom.k,width:el.clientWidth,height:el.clientHeight})')
        for position in saved()['positions'].values():
            assert 0 <= position['x']*transform['k']+transform['x'] <= transform['width']
            assert 0 <= position['y']*transform['k']+transform['y'] <= transform['height']
        page.reload()
        page.locator('.fleet-map[aria-busy=false]').wait_for()
        assert zoom() == pytest.approx(reset['viewport']['zoom'],rel=.01)
        assert saved()['positions']['hud:context']['x'] == pytest.approx(reset['positions']['hud:context']['x'])
        browser.close()
