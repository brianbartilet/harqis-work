"""Nested modal lifecycle, inherited requests, reset and mobile containment."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import time

import pytest


@pytest.mark.parametrize('touch', [False, True])
def test_graph_entities_modal_context(authenticated_client, monkeypatch, tmp_path, touch):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    from workflows.hfl.entity_store import get_store, VERSION
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'entities.sqlite3'))
    row = dict(id='one', title='Project launch', text='React launch', source='notes',
               date='2026-09-20', tags=['project'], path='day.md', anchor='one')
    monkeypatch.setattr(entities, 'current_entries', lambda context='': [row])
    store = get_store()
    store.save('one', entities.entry_hash(row), [entities.mention(row, 'tools', 'React', 'React', 'model-extracted')], VERSION)
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width':1440, 'height':900}, has_touch=touch, is_mobile=touch)
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route_request(route):
                request = route.request
                requests.append(request.url)
                if urlparse(request.url).path == '/modal-host':
                    route.fulfill(content_type='text/html', body='''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>
                    <form id="corpus-search-form"></form><a href="/hfl-corpus/graph">Graph</a>
                    <link rel="stylesheet" href="/static/css/activity-modals.css">
                    <script src="/static/js/activity-modals.js"></script></body></html>''')
                    return
                response = authenticated_client.request(request.method, request.url.replace('http://modal.test',''),
                    content=request.post_data, headers={'content-type':request.headers.get('content-type','application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://modal.test/**', route_request)
            page.goto('http://modal.test/modal-host?source=notes&q=%23project')
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':900 if width == 1440 else 844})
                start = time.monotonic()
                page.get_by_role('link',name='Graph',exact=True).click()
                graph = page.frame_locator('iframe[title="Activity Graph"]')
                graph.locator('#kg-workspace:not([inert])').wait_for()
                print(f'Modal usable ({width}px): {time.monotonic()-start:.2f}s')
                graph_params = parse_qs(urlparse(next(u for u in reversed(requests) if '/entities/graph?' in u)).query)
                assert parse_qs(graph_params['context'][0]) == {'source':['notes'],'q':['#project']}
                if touch and width == 390:
                    canvas = graph.locator('#kg-canvas canvas').first
                    page.wait_for_timeout(1200)
                    initial = canvas.evaluate('(el) => ({x:el.__zoom.x,y:el.__zoom.y,k:el.__zoom.k})')
                    bounds = canvas.bounding_box()
                    x, y = bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2
                    cdp = page.context.new_cdp_session(page)
                    cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
                    for step in range(1, 7):
                        cdp.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':x+step*10,'y':y+step*5}]})
                    cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
                    after = canvas.evaluate('(el) => ({x:el.__zoom.x,y:el.__zoom.y,k:el.__zoom.k})')
                    assert after['x'] - initial['x'] == pytest.approx(60, abs=4)
                    assert after['y'] - initial['y'] == pytest.approx(30, abs=4)
                    assert after['k'] == pytest.approx(initial['k'])
                    graph.locator('#kg-open-views').click()
                    graph.locator('button[data-preset="timeline"]').click()
                    page.wait_for_timeout(1200)
                    page.wait_for_timeout(200)
                    cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
                    for step in range(1, 7):
                        cdp.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':x+step*10,'y':y+step*5}]})
                    cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
                    center = canvas.evaluate('(el) => ({x:(el.clientWidth/2-el.__zoom.x)/el.__zoom.k,y:(el.clientHeight/2-el.__zoom.y)/el.__zoom.k})')
                    page.set_viewport_size({'width':390,'height':800})
                    page.wait_for_timeout(250)
                    resized = canvas.evaluate('(el) => ({x:(el.clientWidth/2-el.__zoom.x)/el.__zoom.k,y:(el.clientHeight/2-el.__zoom.y)/el.__zoom.k})')
                    assert resized['x'] == pytest.approx(center['x'], abs=1)
                    assert resized['y'] == pytest.approx(center['y'], abs=1)
                    cdp.detach()
                graph.locator('#kg-open-filters').click()
                box = graph.locator('#kg-filter-drawer').bounding_box()
                assert box['x'] >= 0 and box['x'] + box['width'] <= width
                source_box = graph.locator('#kg-source-menu').bounding_box()
                assert source_box['width'] > 250
                assert abs(graph.locator('#kg-since').bounding_box()['y'] - graph.locator('#kg-until').bounding_box()['y']) < 2
                assert graph.locator('#kg-rolling').bounding_box()['y'] > graph.locator('#kg-until').bounding_box()['y']
                graph.locator('#kg-source-caption').click()
                choice = graph.locator('#kg-source-options label').first
                assert choice.locator('input').bounding_box()['width'] == 16
                assert choice.bounding_box()['height'] < 50
                page.screenshot(path=str(tmp_path / f'activity-drawer-{width}.png'))
                graph.locator('#kg-source-caption').click()
                graph.locator('#kg-close-filters').click()
                graph.locator('#kg-search').fill('Project')
                page.wait_for_timeout(400)
                graph.locator('#kg-workspace:not([inert])').wait_for()
                graph.locator('#kg-entities').click()
                directory = graph.frame_locator('iframe[title="Activity Corpus Entities"]')
                directory.locator('#entity-results:not([hidden])').wait_for()
                drawer = graph.locator('.activity-entities-drawer')
                bounds = drawer.bounding_box()
                assert bounds['width'] == pytest.approx(width * .3 if width > 760 else width - 14, abs=20)
                assert graph.locator('.activity-modal-loading').count() == 0
                assert directory.locator('html').evaluate('el => el.scrollWidth <= innerWidth')
                toggle = directory.locator('.activity-scope-controls').bounding_box()
                intro = directory.locator('.entity-intro').bounding_box()
                assert intro['y'] - (toggle['y'] + toggle['height']) >= 15
                page.screenshot(path=str(tmp_path / f'entities-drawer-{width}.png'))
                assert directory.locator('.entity-card').count() == 1
                directory.get_by_role('switch',name='All activity').click()
                directory.locator('#entity-results:not([hidden])').wait_for()
                assert directory.get_by_role('switch',name='All activity').get_attribute('aria-checked') == 'true'
                directory.get_by_role('button',name='Close entities',exact=True).click()
                graph.locator('.activity-modal').wait_for(state='detached')
                assert graph.locator('#kg-search').input_value() == 'Project'
                graph.get_by_role('switch',name='All activity').click()
                graph.locator('#kg-workspace:not([inert])').wait_for()
                assert 'context' not in parse_qs(urlparse(next(u for u in reversed(requests) if '/entities/graph?' in u)).query)
                graph.locator('#kg-reset').click()
                graph.locator('#kg-workspace:not([inert])').wait_for()
                assert graph.get_by_role('switch',name='All activity').get_attribute('aria-checked') == 'false'
                assert graph.locator('#kg-search').input_value() == ''
                page.screenshot(path=str(tmp_path / f'activity-modal-{width}.png'))
                print(f'Modal screenshot: {tmp_path / f"activity-modal-{width}.png"}')
                graph.get_by_role('button',name='Close',exact=True).click()
                page.locator('.activity-modal').wait_for(state='detached')
                assert page.url.endswith('source=notes&q=%23project')
            assert not errors, errors
        finally:
            browser.close()
