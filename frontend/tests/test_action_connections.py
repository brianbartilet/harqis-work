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
def test_heatmap_date_connections(ideas, authenticated_client, monkeypatch, width):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from test_hfl_corpus import _document
    from modules.hfl_corpus import router, corpus
    playwright = pytest.importorskip('playwright.sync_api')
    action, _, _ = seed(ideas)
    day = datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
    content = f'## {day} 23:49\nEntry ID: hfl-date-test\nWhat happened: Date connections\n'
    document = _document(day + '.md', text=content, entries=corpus.parse_entries(content), entry_count=1)
    monkeypatch.setattr(router.corpus_index, 'get', lambda path: document)
    monkeypatch.setattr(router.corpus_index, 'documents', lambda: ())
    before = ideas.snapshot()
    response = authenticated_client.get(BASE + '/dates/' + day + '/connections')
    assert response.status_code == 200
    assert response.json()['root'] == 'daily:' + day
    assert 'action:' + action['id'] in {n['id'] for n in response.json()['nodes']}
    assert authenticated_client.get(BASE + '/dates/1900-01-01/connections').status_code == 404
    assert authenticated_client.get(BASE + '/dates/invalid/connections').status_code == 422
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(intercept):
            url = urlparse(intercept.request.url)
            if url.hostname != 'connections.test':
                intercept.abort(); return
            result = authenticated_client.get(url.path + ('?' + url.query if url.query else ''))
            intercept.fulfill(status=result.status_code, body=result.content,
                              headers={'content-type': result.headers.get('content-type', 'text/html')})
        page.route('**/*', route)
        page.goto('https://connections.test/hfl-corpus/document/' + day + '.md')
        assert page.locator('[data-date-connections]').count() == 0
        page.goto('https://connections.test/hfl-corpus')
        page.locator(f'[data-activity-day="{day}"]').click()
        trigger = page.locator('[data-date-connections]')
        controls = page.locator('.activity-day-quick-actions')
        create, pin, show, connections = controls.evaluate("""el =>
            ['summary', '[data-activity-menu-pin]', '[data-activity-menu-document]', '[data-date-connections]']
              .map(selector => el.querySelector(selector).getBoundingClientRect().toJSON())
        """)
        assert abs(create['y'] - pin['y']) < 2
        assert abs(show['y'] - connections['y']) < 2
        assert show['y'] >= create['y'] + create['height']
        assert abs(create['width'] - connections['width']) < 2
        trigger.click()
        preview = page.locator('.action-connections-dialog')
        playwright.expect(preview.get_by_label('Date connections graph', exact=True).locator('canvas')).to_be_visible()
        playwright.expect(preview.locator('.connections-details > h3')).to_have_text(day)
        preview.get_by_role('button', name='Close connections').click()
        playwright.expect(trigger).to_be_focused()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
        browser.close()
    assert ideas.snapshot() == before


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
        day_card = day.locator('[data-followup-id="' + action['id'] + '"]')
        day_results = day_card.locator('.action-results-button').bounding_box()
        day_connections = day_card.locator('.action-connections-button').bounding_box()
        assert abs(day_results['width'] - day_card.locator('.action-view-controls').bounding_box()['width']) < 2
        assert abs(day_results['width'] - day_connections['width']) < 2
        assert day_connections['y'] >= day_results['y'] + day_results['height']
        day.evaluate("el => { el.style.maxHeight = '260px'; el.scrollTop = el.scrollHeight; }")
        header = day.locator('.activity-day-menu-header').bounding_box()
        assert abs(header['y'] - day.bounding_box()['y']) < 2
        actions_header = day.locator('[data-activity-menu-actions]').bounding_box()
        assert abs(actions_header['y'] - header['y'] - header['height']) < 2
        for control in ('[data-activity-menu-date]', '.activity-day-quick-actions'):
            box = day.locator(control).bounding_box()
            assert box['y'] >= header['y']
            assert box['y'] + box['height'] <= header['y'] + header['height']
        day.evaluate("el => { el.style.maxHeight = ''; el.scrollTop = 0; }")
        day.locator('[data-activity-menu-ideas]').click()
        day.locator('[data-day-ideas]').evaluate("el => el.style.minHeight = '800px'")
        day.evaluate("el => { el.style.maxHeight = '260px'; el.scrollTop = 400; }")
        header = day.locator('.activity-day-menu-header').bounding_box()
        ideas_header = day.locator('[data-activity-menu-ideas]').bounding_box()
        assert abs(ideas_header['y'] - header['y'] - header['height']) < 2
        day.locator('[data-activity-menu-ideas]').click()
        day.locator('[data-day-ideas]').evaluate("el => el.style.minHeight = ''")
        day.evaluate("el => { el.style.maxHeight = ''; el.scrollTop = 0; }")
        day.locator('[data-activity-menu-actions]').click()
        trigger = day_card.get_by_role('button', name='Connections', exact=True)
        trigger.click()
        assert day.locator('[data-followup-id="' + isolated['id'] + '"] .action-connections-button').count() == 0
        preview = page.locator('.action-connections-dialog')
        playwright.expect(preview.get_by_role('status')).to_have_text('Loading connections…')
        loading_box = preview.bounding_box()
        page.evaluate('window.releaseConnections()')
        playwright.expect(preview.locator('canvas')).to_be_visible()
        loaded_box = preview.bounding_box()
        playwright.expect(preview.locator('.connections-status')).to_have_text('Open')
        playwright.expect(preview.locator('.connections-status')).to_have_attribute('aria-label', 'Status: Open')
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
        assert connection_box['y'] >= result_box['y'] + result_box['height']
        assert abs(result_box['width'] - connected_card.locator('.action-view-controls').bounding_box()['width']) < 2
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


@pytest.mark.parametrize('touch', [False, True])
def test_board_drag_and_checklist_refresh_keep_connections(ideas, authenticated_client, monkeypatch, touch):
    from modules.hfl_corpus import router
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr(router.corpus_index, 'documents', lambda: ())
    action, _, _ = seed(ideas)
    action = ideas.followups.update(action['id'], {'version':action['version'], 'checklists':[
        {'id':'list', 'title':'Checklist', 'cover':True, 'items':[{'id':'item','text':'Keep the button visible','done':False}]}]}, actor='test')
    other = ideas.followups.create({'request_id':str(uuid4()),'title':'Other card','expected_outcome':'Reorder'},actor='test')[0]
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome',headless=True)
        page = browser.new_page(viewport={'width':390 if touch else 1100,'height':1000},has_touch=touch)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(intercept):
            request=intercept.request; url=urlparse(request.url)
            if url.hostname!='connections.test': intercept.abort(); return
            result=authenticated_client.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data,
                headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            intercept.fulfill(status=result.status_code,body=result.content,headers={'content-type':result.headers.get('content-type','text/html')})
        page.route('**/*',route)
        page.add_init_script("""const fetchOriginal=window.fetch; window.availabilityWaiters=[];
          window.fetch=async (...args)=>{
            if(window.pauseAvailability && String(args[0]).endsWith('/connection-availability'))
              await new Promise(resolve=>window.availabilityWaiters.push(resolve));
            return fetchOriginal(...args);
          };""")
        page.goto('https://connections.test/hfl-corpus')
        page.locator('.corpus-tools > summary').click(); page.locator('[data-followups-open]').click()
        board=page.locator('#followups-board'); lane=board.locator('.followups-lane[data-status=open]')
        card=lane.locator(f'[data-followup-id="{action["id"]}"]')
        other_card=lane.locator(f'[data-followup-id="{other["id"]}"]')
        playwright.expect(card.locator('.action-connections-button')).to_be_visible()
        page.evaluate("""id=>{
          window.pauseAvailability=true; window.connectionGaps=0;
          window.untouchedCard=document.querySelector('#followups-board [data-followup-id="'+id+'"]');
          new MutationObserver(()=>{
            if(!document.querySelector('#followups-board .action-connections-button'))window.connectionGaps++;
          }).observe(document.querySelector('#followups-board'),{childList:true,subtree:true});
        }""",other['id'])
        card.locator('.checklist-card-cover input').check()
        page.wait_for_function("window.availabilityWaiters.length > 0")
        playwright.expect(card.locator('.checklist-card-cover input')).to_be_checked()
        # Include the board's five-second polling cycle with availability unresolved.
        page.wait_for_timeout(5200)
        assert page.evaluate('window.connectionGaps')==0
        assert other_card.evaluate('el=>el===window.untouchedCard')
        assert ideas.followups.get(action['id'])['checklists'][0]['items'][0]['done']
        page.evaluate('window.pauseAvailability=false; window.availabilityWaiters.forEach(resolve=>resolve())')
        handle=other_card.locator('.action-drag-handle'); handle.scroll_into_view_if_needed()
        start=handle.bounding_box(); end=card.bounding_box()
        x=start['x']+start['width']/2; y=start['y']+start['height']/2
        target_x=end['x']+end['width']/2; target_y=end['y']+15
        if touch:
            session=page.context.new_cdp_session(page)
            session.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
            page.wait_for_timeout(250)
            for step in range(1,16):
                session.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x+(target_x-x)*step/15,'y':y+(target_y-y)*step/15}]})
                page.wait_for_timeout(25)
            page.wait_for_timeout(350)
            session.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else:
            page.mouse.move(x,y); page.mouse.down(); page.mouse.move(x+8,y,steps=3)
            page.wait_for_timeout(80)
            page.mouse.move(target_x,target_y,steps=15); page.wait_for_timeout(350); page.mouse.up()
        playwright.expect(lane.locator('[data-followup-id]').first).to_have_attribute('data-followup-id',other['id'])
        playwright.expect(board.locator('[data-board-status]')).to_contain_text('Updates every 5 seconds')
        positions=ideas.followups.board_order()
        assert positions[other['id']]<positions[action['id']]
        assert not errors
        browser.close()
