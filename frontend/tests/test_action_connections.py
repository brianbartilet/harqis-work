from uuid import uuid4
from urllib.parse import urlparse

import pytest
from test_hfl_ideas import ideas, BASE, payload
from test_hfl_boards import board_payload


def seed(ideas):
    action = ideas.followups.create({'request_id': str(uuid4()), 'title': 'Test connections', 'body': '# Template Board\n\n- **Requirements**\n\n<script>alert(1)</script><img src=x onerror=alert(1)>', 'expected_outcome': 'Inspect relations'}, actor='owner')[0]
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
    body_html = next(n for n in data['nodes'] if n['id'] == data['root'])['body_html']
    assert '<h1' in body_html and '<strong>Requirements</strong>' in body_html
    assert '<script' not in body_html and 'onerror=' not in body_html
    thoughts = [n for n in data['nodes'] if n['kind'] == 'drafts']
    assert len(thoughts) == len({n['id'] for n in thoughts}) == 2
    assert {n['boards'][0]['name'] for n in thoughts} == {'Packing board', 'Planning board'}
    shared = [n for n in data['nodes'] if n['id'] == 'idea:' + idea['id']]
    assert len(shared) == 1 and len(shared[0]['boards']) == 2
    assert len([e for e in data['edges'] if e['scope'] == 'board']) == 4
    assert ideas.snapshot() == before


def test_connection_availability_shared_board_only_and_unrelated(ideas, authenticated_client):
    action, _, boards = seed(ideas)
    isolated = ideas.followups.create({'request_id': str(uuid4()), 'title': 'Unrelated', 'expected_outcome': 'None'}, actor='owner')[0]
    response = authenticated_client.get(BASE + '/connection-availability')
    assert response.status_code == 200
    assert action['id'] in response.json()['action_ids']
    assert isolated['id'] not in response.json()['action_ids']
    from modules.hfl_corpus.action_connections import connected_actions
    root = 'action:' + action['id']
    shared = {'nodes': [{'id': root}], 'edges': []}
    assert connected_actions(shared, boards) == [action['id']]
    assert connected_actions(shared, []) == []
    assert connected_actions({'nodes': [], 'edges': []}, boards) == []


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
    isolated = ideas.followups.create({'request_id': str(uuid4()), 'title': 'Unrelated', 'expected_outcome': 'None'}, actor='owner')[0]
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
        page.add_init_script("""
          const originalFetch = window.fetch;
          let first = true;
          window.fetch = async (...args) => {
            if (String(args[0]).endsWith('/connections') && first) {
              first = false;
              await new Promise(resolve => { window.releaseConnections = resolve; });
            }
            return originalFetch(...args);
          };
        """)
        page.goto('https://connections.test/hfl-corpus')
        today = datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
        page.locator(f'[data-activity-day="{today}"]').click()
        day = page.locator('[data-activity-day-menu]')
        trigger = day.get_by_role('button', name='Connections', exact=True)
        trigger.click()
        assert day.locator('[data-followup-id="' + isolated['id'] + '"] .action-connections-button').count() == 0
        preview = page.locator('.action-connections-dialog')
        playwright.expect(preview.get_by_role('status')).to_have_text('Loading connections…')
        loading_box = preview.bounding_box()
        page.evaluate('window.releaseConnections()')
        playwright.expect(preview.locator('canvas')).to_be_visible()
        loaded_box = preview.bounding_box()
        for dimension in ('x', 'y', 'width', 'height'):
            assert abs(loaded_box[dimension] - loading_box[dimension]) < 2
        assert preview.locator('select').count() == 0
        playwright.expect(preview.locator('.connections-body h1')).to_have_text('Template Board')
        playwright.expect(preview.locator('.connections-body strong')).to_have_text('Requirements')
        assert preview.locator('.connections-body script, .connections-body [onerror]').count() == 0
        viewport = preview.get_by_label('Action connections graph', exact=True)
        playwright.expect(viewport.get_by_role('button', name='Fit', exact=True)).to_be_visible()
        viewport.focus()
        for _ in range(4):
            page.keyboard.press('ArrowRight')
            if 'Originating board' in preview.locator('.connections-details').inner_text() and 'Packing board' in preview.locator('.connections-details').inner_text():
                break
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
        playwright.expect(preview.locator('.connections-details > h3')).to_have_text(action['title'])
        preview.get_by_role('button', name='Close connections').click()
        page.keyboard.press('Escape')
        page.locator('.corpus-tools > summary').click()
        page.get_by_role('button', name='Actions Board', exact=True).click()
        board = page.locator('#followups-board')
        board.get_by_role('button', name='Connections', exact=True).click()
        assert board.locator('[data-followup-id="' + isolated['id'] + '"] .action-connections-button').count() == 0
        playwright.expect(preview.locator('canvas')).to_be_visible()
        preview.get_by_role('button', name='Close connections').click()
        playwright.expect(board).to_be_visible()
        connected_card = board.locator('[data-followup-id="' + action['id'] + '"]')
        result_box = connected_card.get_by_role('button', name='Results', exact=True).bounding_box()
        connection_box = connected_card.get_by_role('button', name='Connections', exact=True).bounding_box()
        assert abs(result_box['width'] - connection_box['width']) < 2
        assert abs(result_box['y'] - connection_box['y']) < 2
        management_boxes = [button.bounding_box() for button in connected_card.locator('.action-management-controls button').all()]
        assert max(box['width'] for box in management_boxes) - min(box['width'] for box in management_boxes) < 2
        assert all(box['y'] + box['height'] <= result_box['y'] for box in management_boxes)
        page.screenshot(path=str(tmp_path / f'action-buttons-{width}.png'))
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
