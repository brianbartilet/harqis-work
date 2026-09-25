"""Connection mutations preserve board scope and reject stale shared edits."""
import json

import pytest

from test_hfl_ideas import ideas, BASE
from test_hfl_boards import board_payload


def test_connection_lifecycle_and_shared_revision(ideas, authenticated_client):
    client = authenticated_client
    a, b = ideas.topic('A')['id'], ideas.topic('B')['id']
    board = ideas.save_map(board_payload(members=[a, b]))
    edge = dict(source=a, target=b, relation='supports', direction='both')
    uri = BASE + '/maps/' + board['id']

    def command(operation, **extra):
        return client.post(uri + '/connections', json=dict(version=ideas.map(board['id'])['version'], operation=operation, edge=edge, **extra))

    assert command('create').status_code == 200
    assert command('create').status_code == 422
    assert client.post(uri + '/connections', json=dict(version=ideas.map(board['id'])['version'], operation='create', edge=dict(edge, source=b, target=a))).status_code == 422
    for width in [0, 6, True, 1.5]:
        assert command('width', width=width).status_code == 422
    assert command('width', width=5).status_code == 200
    key = json.dumps([a, b, 'supports'], separators=(',', ':'))
    assert ideas.map(board['id'])['edge_widths'][key] == 5
    assert ideas.links() == []
    result = client.post(uri + '/promote-link', json=dict(version=ideas.map(board['id'])['version'], edge={k: edge[k] for k in ('source', 'target', 'relation')}))
    assert result.status_code == 200, result.text
    original = ideas.links()[0]
    assert original['direction'] == 'both'
    other = ideas.save_map(board_payload(members=[a, b], edge_widths={key: 3}))
    replacement = dict(source=b, target=a, relation='depends-on', direction='none')
    assert command('update', scope='shared', revision='stale', replacement=replacement).status_code == 409
    result = command('update', scope='shared', revision=original['revision'], replacement=replacement)
    assert result.status_code == 200, result.text
    saved = ideas.links()[0]
    assert (saved['source'], saved['target'], saved['direction']) == (b, a, 'none')
    assert saved['revision'] != original['revision']
    new_key = json.dumps([b, a, 'depends-on'], separators=(',', ':'))
    assert ideas.map(other['id'])['edge_widths'] == {new_key: 3}
    assert ideas.map(board['id'])['edge_widths'] == {new_key: 5}
    edge = replacement
    assert command('remove', scope='shared', revision=saved['revision']).status_code == 200
    assert ideas.links() == []
    assert ideas.map(other['id'])['edge_widths'] == {}
    assert ideas.map(board['id'])['members'] == [a, b]


def test_connection_validation_and_board_conflict(ideas, authenticated_client):
    board = ideas.save_map(board_payload(drafts=[dict(id='draft:a', title='A'), dict(id='draft:b', title='B')], root='draft:a'))
    uri = BASE + '/maps/' + board['id'] + '/connections'
    edge = dict(source='draft:a', target='draft:b', relation='related-to')
    for invalid in [dict(edge, target='draft:a'), dict(edge, target='unknown'), dict(edge, direction='invalid')]:
        assert authenticated_client.post(uri, json=dict(version=1, operation='create', edge=invalid)).status_code == 422
    assert authenticated_client.post(uri, json=dict(version=1, operation='create', edge=edge)).status_code == 200
    assert authenticated_client.post(uri, json=dict(version=1, operation='remove', edge=edge)).status_code == 409
    assert authenticated_client.post(uri, json=dict(version=2, operation='remove', edge=edge, scope='shared')).status_code == 409
    assert len(ideas.map(board['id'])['edges']) == 1


@pytest.mark.parametrize('width', [390, 1280])
def test_board_search_preserves_saved_layout(ideas, authenticated_client, width):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    positions = {'draft:a': dict(x=-210, y=75), 'draft:b': dict(x=180, y=-95)}
    board = ideas.save_map(board_payload(root='draft:a', drafts=[dict(id='draft:a', title='Alpha'), dict(id='draft:b', title='Beta')], positions=positions))
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport=dict(width=width, height=1000))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route(intercept):
                req = intercept.request
                url = urlparse(req.url)
                response = authenticated_client.request(req.method, url.path + ('?' + url.query if url.query else ''), content=req.post_data_buffer, headers={'content-type':'application/json'})
                intercept.fulfill(status=response.status_code, body=response.content, headers={'content-type':response.headers.get('content-type','text/html')})
            page.route('**/*', route)
            page.goto('https://boards.test/hfl-corpus/ideas?board='+board['id'])
            count = page.locator('#kg-map-count')
            expect(count).to_have_text('2 nodes · 0 links')
            page.wait_for_function("document.querySelector('#kg-canvas canvas')?.__zoom?.k > 0")
            geometry = '() => ({positions:window.HflIdeas.maps.getPositions(),camera:{...document.querySelector("#kg-canvas canvas").__zoom}})'
            original = page.evaluate(geometry)
            assert original['positions'] == positions
            search = page.locator('#kg-search')
            for query, expected in [('Alpha', 1), ('no matching orb', 0), ('', 2), ('Beta', 1), ('', 2)]:
                search.fill(query)
                expect(count).to_have_text(f'{expected} nodes · 0 links')
                current = page.evaluate(geometry)
                assert current['camera'] == original['camera']
                assert all(p == positions[identity] for identity, p in current['positions'].items())
            assert page.evaluate(geometry)['positions'] == positions
            assert ideas.map(board['id'])['positions'] == positions
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize('width', [390, 1280])
def test_connection_controls_browser(ideas, authenticated_client, width, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    source_id, target_id = ('draft:a', 'draft:b') if width == 390 else (ideas.topic('Alpha')['id'], ideas.topic('Beta')['id'])
    board = ideas.save_map(board_payload(root=source_id, drafts=[dict(id=source_id, title='Alpha'), dict(id=target_id, title='Beta')] if width == 390 else [], members=[] if width == 390 else [source_id,target_id], positions={source_id:dict(x=-100,y=0), target_id:dict(x=100,y=0)}))
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport=dict(width=width, height=1000), has_touch=width==390)
        # Use the actual rendered curve for hit testing, including zoom and DPR.
        page.add_init_script("""(() => {
            const proto=CanvasRenderingContext2D.prototype, move=proto.moveTo, curve=proto.quadraticCurveTo;
            proto.moveTo=function(x,y){this.testStart=[x,y];return move.call(this,x,y);};
            proto.quadraticCurveTo=function(cx,cy,x,y){
                if(this.testStart&&this.canvas.closest('#kg-canvas')){
                    const [sx,sy]=this.testStart, p=this.getTransform().transformPoint({x:sx/4+cx/2+x/4,y:sy/4+cy/2+y/4});
                    const b=this.canvas.getBoundingClientRect();
                    this.canvas.testCurvePoint={x:b.x+p.x*b.width/this.canvas.width,y:b.y+p.y*b.height/this.canvas.height};
                }
                return curve.call(this,cx,cy,x,y);
            };
        })();""")
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(intercept):
            req = intercept.request
            url = urlparse(req.url)
            response = authenticated_client.request(req.method, url.path + ('?' + url.query if url.query else ''), content=req.post_data_buffer, headers={'content-type':'application/json'})
            intercept.fulfill(status=response.status_code, body=response.content, headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*', route)
        page.goto('https://boards.test/hfl-corpus/ideas?board='+board['id'])
        expect(page.locator('#kg-map-count')).to_have_text('2 nodes · 0 links')
        canvas = page.locator('#kg-canvas canvas').first
        page.wait_for_function("document.querySelector('#kg-canvas canvas')?.testCurvePoint || document.querySelector('#kg-canvas canvas')?.__zoom?.k > 0")
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        def point(identity):
            return canvas.evaluate('(el,id)=>{const p=window.HflIdeas.maps.getPositions()[id],z=el.__zoom,b=el.getBoundingClientRect();return {x:b.x+z.x+p.x*z.k,y:b.y+z.y+p.y*z.k}}', identity)
        a, b = point(source_id), point(target_id)
        page.mouse.click(a['x'], a['y'])
        connector = page.get_by_role('button', name='North connector for Alpha')
        expect(connector).to_be_visible()
        if width == 390:
            connector.tap()
            page.touchscreen.tap(b['x'], b['y'])
        else:
            box = connector.bounding_box()
            page.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2)
            page.mouse.down();page.mouse.move(b['x'],b['y'],steps=8);page.mouse.up()
        expect(page.locator('#kg-map-count')).to_have_text('2 nodes · 1 links')
        panel = page.get_by_role('region', name='Connection actions')
        expect(panel).to_be_visible()
        panel.get_by_label('Connection arrows').select_option('both')
        expect(panel.get_by_label('Connection arrows')).to_have_value('both')
        panel.get_by_role('button', name='Reverse direction').click()
        expect(panel.locator('p').first).to_have_text('Beta ↔ Alpha')
        panel.get_by_label('Connection relationship').select_option('supports')
        expect(panel.get_by_label('Connection relationship')).to_have_value('supports')
        increase = panel.get_by_role('button', name='Increase line thickness')
        for _ in range(3):
            increase.click()
            expect(increase).to_be_enabled() if _ < 2 else expect(increase).to_be_disabled()
        page.screenshot(path=str(tmp_path / 'connection-controls.png'))
        panel.get_by_role('button', name='Close', exact=True).click()
        a, b = point(source_id), point(target_id)
        def click_line():
            clear = page.get_by_role('menuitem', name='Clear selection', exact=True)
            if clear.count():
                clear.click()
            page.wait_for_function("document.querySelector('#kg-canvas canvas')?.testCurvePoint")
            page.wait_for_function("""() => {
                const canvas=document.querySelector('#kg-canvas canvas');
                const key=JSON.stringify([canvas.__zoom,canvas.testCurvePoint]);
                if(window.lineTestPoint!==key){window.lineTestPoint=key;window.lineTestChanged=performance.now();return false;}
                // force-graph refreshes its hit-test canvas on an 800ms throttle.
                return performance.now()-window.lineTestChanged>900;
            }""")
            point = canvas.evaluate('el => el.testCurvePoint')
            page.mouse.move(point['x'], point['y'])
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            page.mouse.click(point['x'], point['y'])
        click_line()
        expect(panel).to_be_visible()
        panel.get_by_label('Connection arrows').select_option('none')
        expect(panel.get_by_label('Connection arrows')).to_have_value('none')
        if width == 1280:
            panel.get_by_role('button', name='Share with Activity Graph').click()
            expect(panel).not_to_be_visible()
        page.reload()
        expect(page.locator('#kg-map-count')).to_have_text('2 nodes · 1 links')
        saved = ideas.map(board['id'])
        if width == 390:
            assert saved['edges'] == [dict(source=target_id,target=source_id,relation='supports',direction='none')]
        else:
            assert saved['edges'] == []
            assert ideas.links()[0]['direction'] == 'none'
        assert list(saved['edge_widths'].values()) == [5]
        page.wait_for_function("""() => {
            const z=document.querySelector('#kg-canvas canvas').__zoom;
            const key=JSON.stringify([z.k,z.x,z.y]);
            if(window.settledZoom!==key){window.settledZoom=key;window.zoomChanged=performance.now();return false;}
            return performance.now()-window.zoomChanged>200;
        }""")
        a, b = point(source_id), point(target_id)
        click_line()
        if width == 1280:
            page.screenshot(path=str(tmp_path / 'shared-click.png'))
            expect(panel.locator('strong')).to_have_text('Shared connection')
            panel.get_by_label('Connection arrows').select_option('both')
            expect(panel.get_by_label('Connection arrows')).to_have_value('both')
        panel.get_by_role('button', name='Remove connection').click()
        expect(page.locator('#kg-map-count')).to_have_text('2 nodes · 0 links')
        assert len(ideas.map(board['id'])['drafts' if width == 390 else 'members']) == 2
        assert ideas.links() == []
        assert not errors
        browser.close()
