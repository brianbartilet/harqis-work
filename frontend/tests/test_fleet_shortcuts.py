"""Keyboard parity across the fleet, HUD dashboard and shared Butler."""
from urllib.parse import urlparse
import pytest
import re
from test_hfl_agent_bridge import bridge  # noqa: F401
from test_agent_fleet import fleet  # noqa: F401

@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)])
def test_fleet_work_shortcuts(fleet, authenticated_client, tmp_path, width, height):
    pw=pytest.importorskip('playwright.sync_api')
    fleet.initialize()
    client=authenticated_client
    from modules.hfl_corpus import workspace_views as ws
    ws.save(ws.WorkspaceWrite(name='Keyboard Space',state=ws.WorkspaceState()))
    with pw.sync_playwright() as engine:
        browser=engine.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':width,'height':height})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            u=urlparse(r.request.url)
            if u.path=='/second-brain/hud/data':
                r.fulfill(json={'items':{},'context':[],'source_error':'','spaces':client.get('/hfl-corpus/workspace-views').json(),'layout':{'widgets':[],'version':0}});return
            response=client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://fleet.test/**',route)
        def key(value):
            page.evaluate('document.activeElement?.blur()')
            page.keyboard.press(value)
        try:
            page.goto('https://fleet.test/agents')
            page.get_by_role('complementary',name='Agent work').wait_for()
            key('k')
            help=page.get_by_role('dialog',name='Keyboard shortcuts',exact=True)
            pw.expect(help).to_be_visible()
            pw.expect(help.get_by_text('Show/hide Butler',exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path/'fleet-shortcuts.png'))
            key('b')
            pw.expect(help).not_to_be_visible()
            pw.expect(page.locator('#butler-panel')).to_be_visible()
            page.keyboard.press('Escape')
            key('a')
            pw.expect(page.get_by_role('dialog',name='New action',exact=True)).to_be_visible()
            page.keyboard.press('Escape')
            search=page.get_by_role('searchbox',name='Search agents and outputs')
            search.fill('')
            search.press('b')
            pw.expect(search).to_have_value('b')
            pw.expect(page.locator('#butler-panel')).not_to_be_visible()
            search.fill('')
            key('g')
            page.get_by_label('Name',exact=True).wait_for()
            page.keyboard.press('Escape')
            key('f')
            pw.expect(page.get_by_role('dialog',name='Filters',exact=True)).to_be_visible()
            page.keyboard.press('Escape')
            page.locator('.fleet-spaces .workspace-menu>summary').click()
            panel=page.locator('.fleet-spaces .workspace-menu-panel')
            pw.expect(panel).to_be_visible()
            bounds=panel.bounding_box()
            assert bounds['x']>=0 and bounds['x']+bounds['width']<=width
            switch=panel.get_by_role('switch')
            assert switch.bounding_box()['width']==34
            page.screenshot(path=str(tmp_path/'fleet-spaces.png'))
            page.keyboard.press('Escape')
            first_space=client.get('/hfl-corpus/workspace-views').json()['views'][0]['name']
            key('Alt+1')
            pw.expect(page.locator('.fleet-spaces .activity-view-name')).to_have_text(first_space)
            key('Alt+`')
            pw.expect(page.locator('.fleet-spaces .activity-view-name')).to_have_text('All activity')
            key('Backslash')
            pw.expect(page.locator('#agent-fleet')).to_have_class(re.compile('fleet-fullscreen'))
            key('k')
            pw.expect(help).to_be_visible()
            key('b')
            pw.expect(page.locator('#butler-panel')).to_be_visible()
            page.keyboard.press('Escape')
            key('Backslash')
            key('Tab')
            page.wait_for_url('**/second-brain')
            page.locator('#hud-surface:not([inert])').wait_for()
            motion=page.locator('#hud-motion')
            before=motion.get_attribute('aria-pressed')
            key('Space')
            pw.expect(motion).to_have_attribute('aria-pressed','false' if before=='true' else 'true')
            key('k')
            pw.expect(page.locator('#hud-hotkeys-dialog')).to_be_visible()
            pw.expect(page.locator('#hud-hotkeys-dialog').get_by_text('Back to agents fleet',exact=True)).to_be_visible()
            key('b')
            pw.expect(page.locator('#butler-panel')).to_be_visible()
            page.keyboard.press('Escape')
            key('Tab')
            page.wait_for_url('**/agents*')
            assert not errors,errors
        finally:
            browser.close()
