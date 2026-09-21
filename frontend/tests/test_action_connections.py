from uuid import uuid4
from urllib.parse import urlparse

import pytest
from test_hfl_ideas import ideas, BASE, payload
from test_hfl_boards import board_payload


def seed(ideas):
    action = ideas.followups.create({'request_id': str(uuid4()), 'title': 'Test connections', 'expected_outcome': 'Inspect relations'}, actor='owner')[0]
    root = 'action:' + action['id']
    idea = ideas.save_idea(payload(title='Shared possibility'), 'owner')
    neighbor = 'idea:' + idea['id']
    ideas.link(root, neighbor, 'related-to')
    boards = [ideas.save_map(board_payload(name=name, members=[root, neighbor],
              edges=[{'source': root, 'target': 'draft:seed', 'relation': 'supports', 'direction': 'both'},
                     {'source': root, 'target': neighbor, 'relation': 'depends-on', 'direction': 'none'}]))
              for name in ('Packing board', 'Planning board')]
    return action, idea, boards


def test_connections_include_board_thoughts_and_preserve_shared_identity(ideas, authenticated_client):
    action, idea, boards = seed(ideas)
    before = ideas.snapshot()
    response = authenticated_client.get(BASE + '/actions/' + action['id'] + '/connections')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['root'] == 'action:' + action['id']
    thoughts = [n for n in data['nodes'] if n['kind'] == 'drafts']
    assert len(thoughts) == len({n['id'] for n in thoughts}) == 2
    assert {n['boards'][0]['name'] for n in thoughts} == {'Packing board', 'Planning board'}
    shared = [n for n in data['nodes'] if n['id'] == 'idea:' + idea['id']]
    assert len(shared) == 1 and len(shared[0]['boards']) == 2
    assert len([e for e in data['edges'] if e['scope'] == 'board']) == 4
    assert ideas.snapshot() == before


def test_connections_protected_action_is_unavailable(ideas, authenticated_client):
    action = ideas.followups.create({'request_id': str(uuid4()), 'title': 'Protected', 'expected_outcome': 'Inspect relations'}, actor='owner',
                                   source={'path':'secret.md', 'entry_id':'hidden'})[0]
    assert authenticated_client.get(BASE + '/actions/' + action['id'] + '/connections').status_code == 404
    assert authenticated_client.get(BASE + '/actions/missing/connections').status_code == 404


def test_projection_empty_protected_neighbors_and_direct_depth():
    from modules.hfl_corpus.action_connections import project
    root = {'id':'action:a', 'kind':'actions', 'label':'Action'}
    shared = {'nodes':[root, {'id':'idea:b'}, {'id':'idea:c'}], 'edges':[
        {'source':'action:a', 'target':'idea:b', 'relation':'related-to'},
        {'source':'idea:b', 'target':'idea:c', 'relation':'related-to'}]}
    board = {'id':'map-a', 'name':'Board', 'members':['action:a', 'idea:protected'],
             'edges':[{'source':'action:a', 'target':'idea:protected', 'relation':'related-to'}]}
    data = project('a', shared, [board])
    assert {n['id'] for n in data['nodes']} == {'action:a', 'idea:b'}
    assert len(data['edges']) == 1
    assert project('a', {'nodes':[root], 'edges':[]}, [])['edges'] == []


@pytest.mark.parametrize('width', [390, 1100])
def test_connections_preview_both_cards_and_throwaway_lifecycle(ideas, authenticated_client, monkeypatch, tmp_path, width):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from modules.hfl_corpus import router
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr(router.corpus_index, 'documents', lambda: ())
    action, idea, boards = seed(ideas)
    before = ideas.snapshot()
    requests = []
    mode = {'value':'normal'}
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':width, 'height':900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(intercept):
            request = intercept.request
            url = urlparse(request.url)
            if url.hostname != 'connections.test':
                intercept.abort(); return
            if url.path.endswith('/connections'):
                requests.append(request.method)
                if mode['value'] == 'error':
                    intercept.fulfill(status=502, json={'detail':'Unavailable'}); return
                if mode['value'] == 'empty':
                    intercept.fulfill(json={'root':'action:'+action['id'], 'nodes':[], 'edges':[]}); return
            response = authenticated_client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                         content=request.post_data, headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            intercept.fulfill(status=response.status_code, body=response.content,
                              headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*', route)
        page.goto('https://connections.test/hfl-corpus')
        today = datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
        page.locator(f'[data-activity-day="{today}"]').click()
        day = page.locator('[data-activity-day-menu]')
        trigger = day.get_by_role('button', name='Connections', exact=True)
        trigger.click()
        preview = page.locator('.action-connections-dialog')
        playwright.expect(preview.locator('canvas')).to_be_visible()
        picker = preview.get_by_label('Inspect orb')
        picker.select_option('board:' + boards[0]['id'] + ':draft:seed')
        playwright.expect(preview.locator('.connections-details')).to_contain_text('Originating board')
        playwright.expect(preview.locator('.connections-details')).to_contain_text('Packing board')
        assert preview.get_by_role('button', name='Edit', exact=True).count() == 0
        preview.get_by_role('button', name='Fit', exact=True).click()
        canvas = preview.locator('canvas').bounding_box()
        page.mouse.move(canvas['x'] + canvas['width']/2, canvas['y'] + canvas['height']/2)
        page.mouse.down(); page.mouse.move(canvas['x'] + canvas['width']/2 + 35, canvas['y'] + canvas['height']/2 + 25, steps=5); page.mouse.up()
        page.screenshot(path=str(tmp_path / f'connections-{width}.png'))
        box = preview.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width
        assert box['y'] >= 0 and box['y'] + box['height'] <= 900
        page.keyboard.press('Escape')
        playwright.expect(preview).to_have_count(0)
        playwright.expect(day).to_be_visible()
        trigger.click()
        playwright.expect(preview.get_by_label('Inspect orb')).to_have_value('action:' + action['id'])
        preview.get_by_role('button', name='Close connections').click()
        page.keyboard.press('Escape')
        page.locator('.corpus-tools > summary').click()
        page.get_by_role('button', name='Actions Board', exact=True).click()
        board = page.locator('#followups-board')
        board.get_by_role('button', name='Connections', exact=True).click()
        playwright.expect(preview.locator('canvas')).to_be_visible()
        preview.get_by_role('button', name='Close connections').click()
        playwright.expect(board).to_be_visible()
        mode['value'] = 'error'
        board.get_by_role('button', name='Connections', exact=True).click()
        playwright.expect(preview.get_by_role('alert')).to_contain_text('could not load')
        mode['value'] = 'empty'
        preview.get_by_role('button', name='Retry').click()
        playwright.expect(preview).to_contain_text('No connections available.')
        preview.get_by_role('button', name='Close connections').click()
        assert requests == ['GET'] * 5
        assert not errors
        assert ideas.snapshot() == before
        browser.close()
