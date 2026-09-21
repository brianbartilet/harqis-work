"""Boards preserve speculative planning while Goals remain reusable outcomes."""
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas, BASE, payload


def board_payload(**changes):
    return {'request_id': str(uuid4()), 'name': 'Faster fulfillment', 'purpose': 'Compare improvements',
            'root': 'draft:seed', 'drafts': [{'id': 'draft:seed', 'title': 'Packing', 'body': 'Try batching'}], **changes}


def test_board_orb_sizes_validate_and_survive_promotion(ideas, authenticated_client):
    client = authenticated_client
    board = client.post(BASE+'/maps', json=board_payload(node_sizes={'draft:seed':20})).json()['item']
    uri = BASE+'/maps/'+board['id']
    for invalid in [0, 21, True, 2.5, '5']:
        assert client.patch(uri, json={'version':1,'node_sizes':{'draft:seed':invalid}}).status_code == 422
    promoted = client.post(uri+'/promote', json={'version':1,'draft_id':'draft:seed'}).json()
    restored = client.get(uri).json()['item']
    assert restored['node_sizes'] == {'idea:'+promoted['idea_id']:20}
    removed = client.patch(uri, json={'version':restored['version'],'members':[],'root':'','positions':{}})
    assert removed.status_code == 200, removed.text
    assert removed.json()['item']['node_sizes'] == {}


@pytest.mark.parametrize('width', [390, 1280])
def test_board_free_drag_and_orb_sizes_browser(ideas, authenticated_client, width, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    board = ideas.save_map(board_payload(
        drafts=[{'id':'draft:seed','title':'Create a thought to brainstorm and refine, promote as idea','body':''},
                {'id':'draft:next','title':'Keep this thought in place','body':''}],
        edges=[{'source':'draft:seed','target':'draft:next','relation':'related-to'}],
        positions={'draft:seed':{'x':-100,'y':0},'draft:next':{'x':100,'y':0}}))
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':width,'height':1000})
        page.add_init_script('''const paintText=CanvasRenderingContext2D.prototype.fillText;
            CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...rest){
                if(String(text).startsWith('Create a thought'))window.boardTitlePosition={x,y};
                return paintText.call(this,text,x,y,...rest);
            };''')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(intercept):
            req = intercept.request
            url = urlparse(req.url)
            response = authenticated_client.request(req.method, url.path+('?' + url.query if url.query else ''),
                content=req.post_data_buffer, headers={'content-type':'application/json'})
            intercept.fulfill(status=response.status_code, body=response.content,
                headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*', route)
        page.goto('https://boards.test/hfl-corpus/ideas?board='+board['id'])
        expect(page.locator('#kg-map-count')).to_have_text('2 nodes · 1 links')
        canvas = page.locator('#kg-canvas canvas').first
        page.wait_for_function("document.querySelector('#kg-canvas canvas')?.__zoom?.k > 0")
        before = page.evaluate('window.HflIdeas.maps.getPositions()')
        def screen_point(identity):
            return canvas.evaluate('''(el,id) => {const p=window.HflIdeas.maps.getPositions()[id],z=el.__zoom,b=el.getBoundingClientRect();return {x:b.x+z.x+p.x*z.k,y:b.y+z.y+p.y*z.k};}''', identity)
        point = screen_point('draft:seed')
        page.mouse.move(point['x'],point['y'])
        expect(page.get_by_role('button', name='Increase orb size')).to_be_visible()
        page.mouse.down()
        page.mouse.move(point['x']+25,point['y']+65,steps=12)
        page.mouse.up()
        page.evaluate('window.HflIdeas.maps.flush()')
        after = page.evaluate('window.HflIdeas.maps.getPositions()')
        assert after['draft:next'] == before['draft:next']
        assert after['draft:seed'] != before['draft:seed']
        point = screen_point('draft:seed')
        page.mouse.click(point['x'],point['y'])
        menu = page.get_by_role('menu', name='Orb actions')
        expect(menu).to_be_visible()
        menu.get_by_role('menuitem', name='Edit thought', exact=True).focus()
        expect(page.locator('#kg-detail > button')).to_have_count(0)
        page.keyboard.press('End')
        expect(menu.get_by_role('menuitem', name='Clear selection', exact=True)).to_be_focused()
        page.screenshot(path=str(tmp_path / ('board-actions-'+str(width)+'.png')))
        page.keyboard.press('Escape')
        expect(menu).to_have_count(0)
        point = screen_point('draft:seed')
        page.mouse.click(point['x'],point['y'])
        menu.get_by_role('menuitem', name='Edit thought', exact=True).click()
        expect(page.get_by_role('dialog', name='Edit thought', exact=True)).to_be_visible()
        page.keyboard.press('Escape')
        increase = page.get_by_role('button', name='Increase orb size')
        for _ in range(17): increase.click()
        expect(increase).to_be_disabled()
        expect(page.locator('.kg-orb-size output')).to_have_count(0)
        page.evaluate('window.HflIdeas.maps.flush()')
        assert ideas.map(board['id'])['node_sizes']['draft:seed'] == 20
        page.screenshot(path=str(tmp_path / ('board-orbs-'+str(width)+'.png')))
        page.reload()
        expect(page.locator('#kg-map-count')).to_have_text('2 nodes · 1 links')
        page.wait_for_function('window.HflIdeas?.maps?.getPositions && Object.keys(window.HflIdeas.maps.getPositions()).length === 2')
        assert page.evaluate('window.HflIdeas.maps.getPositions()') == after
        point = screen_point('draft:seed')
        page.mouse.click(point['x'],point['y'])
        expect(page.locator('.kg-orb-size output')).to_have_count(0)
        decrease = page.get_by_role('button', name='Decrease orb size')
        for _ in range(19): decrease.click()
        expect(decrease).to_be_disabled()
        expect(page.locator('.kg-orb-size output')).to_have_count(0)
        page.get_by_role('menuitem', name='Clear selection', exact=True).click()
        resting = page.evaluate('window.HflIdeas.maps.getPositions()')
        for mode in ['breathing', 'ripple', 'drift']:
            page.locator('#kg-open-animation').click()
            page.locator('[data-animation="'+mode+'"]').click()
            expect(page.locator('#kg-canvas')).to_have_attribute('data-motion', mode)
            position = page.evaluate('window.boardTitlePosition')
            page.wait_for_function('p => Math.hypot(window.boardTitlePosition.x-p.x,window.boardTitlePosition.y-p.y) > .02', arg=position)
            assert page.evaluate('window.HflIdeas.maps.getPositions()') == resting
        page.evaluate('window.HflIdeas.maps.saveLayout().then(() => window.HflIdeas.maps.flush())')
        assert ideas.map(board['id'])['positions'] == resting
        page.locator('#kg-open-animation').click()
        page.locator('[data-animation=off]').click()
        expect(page.locator('#kg-canvas')).to_have_attribute('data-motion', 'off')
        assert not errors, errors
        browser.close()


def test_board_colors_and_order_persist_without_revising_contents(ideas, authenticated_client):
    from workflows.hfl.ideas_store import IdeasStore
    client = authenticated_client
    palette = client.get(BASE + '/boards').json()['palette']
    first = client.post(BASE + '/maps', json=board_payload(color=palette[4])).json()['item']
    second = client.post(BASE + '/maps', json=board_payload()).json()['item']
    assert first['color'] == palette[4]
    assert client.patch(BASE+'/maps/'+first['id'], json={'version':1, 'color':'invalid'}).status_code == 422
    assert client.put(BASE+'/boards/order', json={'ids':[second['id'], first['id']]}).status_code == 200
    restored = IdeasStore(ideas.followups).maps()
    assert [b['id'] for b in restored] == [second['id'], first['id']]
    assert all(b['version'] == 1 for b in restored)
    assert client.put(BASE+'/boards/order', json={'ids':[second['id']]}).status_code == 409
    assert client.put(BASE+'/boards/order', json={'ids':[second['id'],second['id']]}).status_code == 422


def test_goal_colors_and_order_persist_without_memory_noise(ideas, authenticated_client):
    from workflows.hfl.ideas_store import IdeasStore
    client=authenticated_client
    first=client.post(BASE+'/goals',json={'request_id':str(uuid4()),'title':'First','color':'#8b5cf6'}).json()['item']
    second=client.post(BASE+'/goals',json={'request_id':str(uuid4()),'title':'Second'}).json()['item']
    assert client.put(BASE+'/goals/order',json={'ids':[second['id'],first['id']]}).status_code==200
    restored=IdeasStore(ideas.followups).goals()
    assert [g['id'] for g in restored]==[second['id'],first['id']]
    assert restored[1]['color']=='#8b5cf6'
    assert all(g['version']==1 for g in restored)
    assert client.patch(BASE+'/goals/'+first['id'],json={'version':1,'color':'#14b8a6'}).status_code==200
    assert client.patch(BASE+'/goals/'+first['id'],json={'version':2,'color':'bad'}).status_code==422
    assert client.put(BASE+'/goals/order',json={'ids':[first['id']]}).status_code==409
    assert client.put(BASE+'/goals/order',json={'ids':[first['id'],first['id']]}).status_code==422
    with ideas.followups.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM board_memories').fetchone()[0]==2


def test_manual_goal_options_and_linked_save_skip_graph_and_corpus(ideas, authenticated_client, monkeypatch):
    from modules.hfl_corpus import ideas_api, entities
    idea = ideas.save_idea(payload(), 'owner')
    def unavailable(*a, **kw):
        raise AssertionError('Manual goal links must not build the corpus graph')
    monkeypatch.setattr(ideas_api, 'catalogue', unavailable)
    monkeypatch.setattr(entities, 'current_entries', unavailable)
    response = authenticated_client.get(BASE+'/goal-options')
    assert response.status_code == 200
    assert any(n['id']=='idea:'+idea['id'] for n in response.json()['nodes'])
    # Unrelated generated/protected ideas must not force a corpus scan on save.
    ideas.save_idea(payload(source={'entry_id':'hidden','path':'private.md'}), 'owner')
    response = authenticated_client.post(BASE+'/goals', json={
        'request_id':str(uuid4()),'title':'Outcome','linked_objects':['idea:'+idea['id']]})
    assert response.status_code == 200, response.text


def test_goal_options_do_not_expose_protected_source_objects(ideas, authenticated_client):
    hidden = ideas.save_idea(payload(source={'entry_id':'hidden','path':'private.md'}), 'owner')
    assert authenticated_client.get(BASE+'/goal-options').json()['nodes'] == []
    assert authenticated_client.post(BASE+'/goals', json={
        'request_id':str(uuid4()),'title':'Outcome','linked_objects':['idea:'+hidden['id']]}).status_code == 404


def test_board_sidebar_order_collapse_and_saved_lines_browser(ideas, authenticated_client, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    first = ideas.save_map(board_payload(name='First board', color='#8b5cf6',
        drafts=[{'id':'draft:seed','title':'Packing'}, {'id':'draft:next','title':'Second thought'}],
        edges=[{'source':'draft:seed','target':'draft:next','relation':'supports'}]))
    second = ideas.save_map(board_payload(name='Second board'))
    goal1=ideas.save_goal({'request_id':str(uuid4()),'title':'First goal','color':'#8b5cf6'},'owner')
    goal2=ideas.save_goal({'request_id':str(uuid4()),'title':'Second goal','color':'#14b8a6'},'owner')
    supporting=ideas.save_idea(payload(title='Supporting board idea'), 'owner')
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width':1440,'height':1000})
            page.add_init_script('''const stroke=CanvasRenderingContext2D.prototype.stroke;
                window.boardLineStrokes=0;
                CanvasRenderingContext2D.prototype.stroke=function(...args){
                  if(this.getLineDash().join(',')==='4,3')window.boardLineStrokes++;
                  return stroke.apply(this,args);
                };''')
            def respond(route):
                r=route.request;url=urlparse(r.url)
                response=authenticated_client.request(r.method,url.path+('?' + url.query if url.query else ''),
                    content=r.post_data_buffer,headers={'content-type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,
                    headers={'content-type':response.headers.get('content-type','text/html')})
            page.route('https://sidebar.test/**',respond)
            page.goto('https://sidebar.test/hfl-corpus/graph?board='+first['id'])
            page.wait_for_selector('#kg-workspace:not([inert])')
            sidebar=page.locator('.kg-boards')
            expect(sidebar.get_by_role('button',name='Explore Activity Graph')).to_be_visible()
            assert sidebar.locator('.board-controls button').all_text_contents()==[
                'Add thought','Attach existing','Ask agent','Save now','Save layout','Settings','Delete']
            width=sidebar.bounding_box()['width']
            sidebar.locator('[data-section=boards] > summary').click()
            expect(sidebar.locator('[data-section=boards] .board-list')).not_to_be_visible()
            expect(sidebar.get_by_role('button',name='Settings',exact=True)).to_be_visible()
            assert sidebar.bounding_box()['width']==width
            sidebar.locator('[data-section=boards] > summary').click()
            expect(sidebar.locator('[data-section=goals] .board-list')).not_to_be_visible()
            button_sizes=sidebar.locator('.board-explore,.board-add-menu>.idea-add-toggle,.board-controls>button').evaluate_all('(buttons)=>buttons.map(b=>({width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height}))')
            with page.expect_response(lambda r: r.url.endswith('/boards/order') and r.request.method=='PUT'):
                sidebar.locator('[data-board-id="'+second['id']+'"]').drag_to(sidebar.locator('[data-board-id="'+first['id']+'"]'))
            expect(sidebar.locator('.idea-map-status')).to_be_empty()
            assert [b['id'] for b in ideas.maps()]==[second['id'],first['id']]
            sidebar.locator('[data-section=goals] > summary').click()
            assert sidebar.locator('.board-explore,.board-add-menu>.idea-add-toggle,.board-controls>button').evaluate_all('(buttons)=>buttons.map(b=>({width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height}))')==button_sizes
            with page.expect_response(lambda r: r.url.endswith('/goals/order') and r.request.method=='PUT'):
                sidebar.locator('[data-goal-id="'+goal2['id']+'"]').drag_to(sidebar.locator('[data-goal-id="'+goal1['id']+'"]'))
            expect(sidebar.locator('.idea-map-status')).to_be_empty()
            assert [g['id'] for g in ideas.goals()]==[goal2['id'],goal1['id']]
            sidebar.locator('[data-goal-id="'+goal1['id']+'"]').click()
            editor=page.locator('.idea-dialog')
            expect(sidebar.locator('[data-goal-id="'+goal1['id']+'"] .goal-card-count')).to_have_text('0/0 milestones')
            picker=editor.locator('.goal-link-picker').first
            picker.locator('summary').click()
            picker.get_by_role('searchbox').fill('Supporting board idea')
            picker.get_by_role('checkbox',name='Supporting board idea idea',exact=True).check()
            expect(picker.locator('.goal-link-count')).to_have_text('1 selected')
            editor.get_by_role('button',name='Add milestone',exact=True).click()
            editor.get_by_label('Milestone',exact=True).fill('Verify outcome')
            editor.get_by_label('Milestone status',exact=True).select_option(label='Achieved')
            editor.get_by_label('Status',exact=True).select_option(label='Active')
            page.screenshot(path=str(tmp_path/'goal-editor.png'))
            editor.get_by_role('button',name='Color #f43f5e',exact=True).click()
            page.evaluate('window.HflIdeas.maps.goalsOpen=false')
            editor.get_by_role('button',name='Save Goal',exact=True).click()
            expect(editor).to_have_count(0)
            expect(sidebar.locator('[data-section=goals] .board-list')).to_be_visible()
            assert ideas.goal(goal1['id'])['color']=='#f43f5e'
            assert ideas.goal(goal1['id'])['linked_objects']==['idea:'+supporting['id']]
            expect(sidebar.locator('[data-goal-id="'+goal1['id']+'"] .goal-card-count')).to_have_text('1/1 milestones')
            assert ideas.map(first['id'])['members']==[]
            sidebar.locator('[data-section=goals] > summary').click()
            expect(sidebar.locator('[data-section=goals] nav')).not_to_be_visible()
            expect(sidebar.get_by_role('button',name='Add',exact=True)).to_be_visible()
            sidebar.locator('[data-section=goals] > summary').click()
            page.wait_for_function('window.boardLineStrokes>0')
            page.evaluate('window.boardLineStrokes=0')
            sidebar.get_by_role('button',name='Add thought',exact=True).click()
            page.get_by_label('Thought',exact=True).fill('After save')
            page.get_by_role('button',name='Save thought',exact=True).click()
            sidebar.get_by_role('button',name='Save now',exact=True).click()
            expect(sidebar.locator('.idea-map-status')).to_have_text('Saved')
            page.wait_for_function('window.boardLineStrokes>0')
            expect(page.locator('#kg-map-count')).to_contain_text('2 links')
            page.screenshot(path=str(tmp_path/'board-sidebar.png'))
            page.reload()
            page.wait_for_selector('#kg-workspace:not([inert])')
            expect(sidebar.locator('[data-section=goals] .board-list')).not_to_be_visible()
            sidebar.locator('[data-section=goals] > summary').click()
            expect(page.locator('#kg-map-count')).to_contain_text('2 links')
            assert sidebar.locator('[data-section=boards] .goal-card-title').first.inner_text()=='Second board'
            board_card=sidebar.locator('[data-board-id="'+first['id']+'"]')
            expect(board_card.locator('.goal-status-pill')).to_have_text('Selected')
            expect(board_card.locator('.goal-card-count')).to_have_text('3 nodes')
            expect(sidebar.locator('[data-board-id="'+second['id']+'"] .goal-status-pill')).to_have_text('Saved')
            assert board_card.bounding_box()['height']==sidebar.locator('[data-goal-id="'+goal1['id']+'"]').bounding_box()['height']
            assert sidebar.locator('[data-section=goals] .goal-card-title').first.inner_text()=='Second goal'
            assert sidebar.locator('[data-goal-id="'+goal1['id']+'"]').evaluate('(el)=>getComputedStyle(el).borderLeftColor')=='rgb(244, 63, 94)'
        finally:
            browser.close()


def test_board_metadata_and_draft_graph_do_not_scan_corpus(ideas, authenticated_client, monkeypatch):
    from modules.hfl_corpus import ideas_api
    def unavailable():
        raise AssertionError('Draft-only board operations must not scan the corpus')
    monkeypatch.setattr(ideas_api, 'catalogue', unavailable)
    monkeypatch.setattr(ideas_api, 'permitted_snapshot', unavailable)
    client = authenticated_client
    raw = board_payload(board_date='2026-09-21')
    board = client.post(BASE + '/maps', json=raw).json()['item']
    assert board['created_at'] and board['updated_at'] and board['board_date'] == '2026-09-21'
    assert client.post(BASE + '/maps', json=raw).json()['item'] == board
    assert client.get(BASE + '/boards').json()['maps'] == [board]
    uri = BASE + '/maps/' + board['id']
    assert client.get(uri).json()['item'] == board
    assert client.get(uri + '/graph').json()['nodes'] == []
    updated = client.patch(uri, json={'version':1,'board_date':'2026-09-22'}).json()['item']
    assert updated['created_at'] == board['created_at']
    assert updated['board_date'] == '2026-09-22'
    assert client.patch(uri,json={'version':2,'board_date':'bad'}).status_code == 422


def test_board_date_and_goal_are_linked_without_exposing_drafts(ideas, authenticated_client):
    from modules.hfl_corpus.ideas_graph import extend
    goal = ideas.save_goal({'request_id':str(uuid4()),'title':'Outcome'}, 'owner')
    board = ideas.save_map(board_payload(board_date='2026-09-21', goal_id=goal['id'], members=['goal:'+goal['id']]))
    result = extend({'nodes':[],'edges':[]}, ideas.snapshot(), since='2026-09-21', until='2026-09-21', limit=0)
    node = 'board:' + board['id']
    assert any(n['id'] == node and n['kind'] == 'boards' for n in result['nodes'])
    assert any(e['source'] == node and e['target'] == 'daily:2026-09-21' for e in result['edges'])
    assert not any(n['id'].startswith('draft:') for n in result['nodes'])
    outside = extend({'nodes':[],'edges':[]}, ideas.snapshot(), since='2026-09-22', until='2026-09-22', limit=0)
    assert not any(n['id'] == node for n in outside['nodes'])


def test_board_graph_keeps_permitted_derived_edges_only(ideas, authenticated_client, monkeypatch):
    from modules.hfl_corpus import entities
    members = ['idea:visible', 'goal:visible', 'idea:protected']
    board = ideas.save_map(board_payload(members=members))
    edge = {'source':members[0], 'target':members[1], 'relation':'supports', 'method':'goal'}
    monkeypatch.setattr(entities, 'graph', lambda **kwargs: {
        'nodes':[{'id':members[0]}, {'id':members[1]}, {'id':'idea:outside'}],
        'edges':[edge, {'source':members[0], 'target':'idea:outside','relation':'related-to'}]})
    data = authenticated_client.get(BASE + '/maps/' + board['id'] + '/graph').json()
    assert {n['id'] for n in data['nodes']} == set(members[:2])
    assert data['edges'] == [edge]


@pytest.mark.parametrize('width', [390, 1280])
def test_board_edits_work_while_save_is_slow_and_retry(ideas, authenticated_client, width, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':width,'height':1000})
        pending, graph_requests, errors = [], [], []
        hold = False
        page.on('pageerror', lambda error: errors.append(str(error)))
        def respond(route):
            r = route.request
            u = urlparse(r.url)
            response = authenticated_client.request(r.method, u.path + ('?' + u.query if u.query else ''),
                content=r.post_data_buffer, headers={'content-type':'application/json'})
            route.fulfill(status=response.status_code, body=response.content,
                          headers={'content-type':response.headers.get('content-type','text/html')})
        def route_request(route):
            u = urlparse(route.request.url)
            if u.path == '/hfl-corpus':
                route.fulfill(body='<html>Closed after saving</html>', content_type='text/html')
                return
            if u.path == '/api/hfl/entities/graph': graph_requests.append(u.path)
            if hold and route.request.method == 'PATCH' and '/ideas/maps/' in u.path:
                pending.append(route)
            else: respond(route)
        page.route('https://boards.test/**', route_request)
        try:
            page.goto('https://boards.test/hfl-corpus/graph')
            page.wait_for_selector('#kg-workspace:not([inert])')
            if width < 760: page.locator('.kg-boards [data-section=boards] > summary').click()
            count = len(graph_requests)
            page.locator('.board-add-menu').get_by_role('button',name='Add',exact=True).click()
            page.locator('.board-add-menu').get_by_role('button',name='Board',exact=True).click()
            dialog = page.locator('.idea-dialog')
            dialog.get_by_label('Board name').fill('Quick board')
            dialog.get_by_label('What are you exploring or trying to achieve?').fill('Plan without waiting')
            dialog.get_by_role('button',name='Save board',exact=True).click()
            expect(page.locator('#kg-map-count')).to_contain_text('1 nodes')
            hold = True
            page.locator('.board-controls').get_by_role('button',name='Add thought',exact=True).click()
            dialog.get_by_label('Thought',exact=True).fill('Second thought')
            dialog.get_by_role('button',name='Save thought',exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.locator('#kg-map-count')).to_contain_text('2 nodes')
            page.wait_for_timeout(600)
            assert pending, 'Expected a background save to be held'
            page.locator('#kg-list button').filter(has_text='Second thought').click()
            viewport = page.locator('#kg-canvas canvas').first.evaluate('(el)=>({...el.__zoom})')
            page.get_by_role('button',name='Connect on this board',exact=True).click()
            expect(dialog.get_by_label('Connect to')).to_be_visible(timeout=1000)
            dialog.get_by_label('Relationship',exact=True).select_option('supports')
            dialog.get_by_role('button',name='Save connection',exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.locator('#kg-detail')).to_contain_text('Second thought')
            assert page.locator('#kg-canvas canvas').first.evaluate('(el)=>({...el.__zoom})') == viewport
            assert len(graph_requests) == count
            pending.pop().fulfill(status=503,json={'detail':'Temporarily offline'})
            expect(page.locator('.idea-map-status')).to_contain_text('Unsaved')
            hold = False
            page.get_by_role('button',name='Retry save',exact=True).click()
            expect(page.locator('.idea-map-status')).to_have_text('Saved')
            assert len(ideas.maps()[0]['drafts']) == 2
            assert len(ideas.maps()[0]['edges']) == 2
            for kind in ['Idea', 'Actionable']:
                page.get_by_role('button',name='Create linked '+kind,exact=True).click()
                dialog.locator('[name=title]').fill('Linked '+kind)
                if kind == 'Actionable':
                    dialog.locator('.action-details > summary').click()
                    dialog.get_by_label('Expected outcome').fill('Validate this thought')
                dialog.get_by_role('button',name='Save',exact=True).click()
                page.wait_for_timeout(250)
                if dialog.count():
                    assert not dialog.locator('.idea-error').inner_text(), dialog.inner_text()
                expect(dialog).to_have_count(0)
                expect(page.locator('.idea-map-status')).to_have_text('Saved')
            assert len(ideas.ideas()) == 1
            assert len(ideas.followups.list()) == 1
            assert len(ideas.maps()[0]['drafts']) == 2
            assert len(ideas.maps()[0]['members']) == 2
            assert ideas.links() == []
            assert len(graph_requests) == count
            assert not errors, errors
            page.screenshot(path=str(tmp_path / f'board-autosave-{width}.png'))
            hold = True
            page.get_by_role('button',name='Edit thought',exact=True).click()
            dialog.get_by_label('Thought',exact=True).fill('Saved before closing')
            dialog.get_by_role('button',name='Save thought',exact=True).click()
            page.locator('[data-activity-close]').click()
            page.wait_for_timeout(150)
            assert pending and '/hfl-corpus/graph' in page.url
            hold = False
            respond(pending.pop())
            page.wait_for_url('https://boards.test/hfl-corpus')
            assert any(t['title'] == 'Saved before closing' for t in ideas.maps()[0]['drafts'])
        finally:
            browser.close()


def test_board_drafts_promotion_and_delete_preserve_shared_objects(ideas, authenticated_client):
    client = authenticated_client
    board = client.post(BASE + '/maps', json=board_payload()).json()['item']
    uri = BASE + '/maps/' + board['id']
    assert ideas.ideas() == []
    assert not any(n['kind'] == 'drafts' for n in client.get('/api/hfl/entities/graph?limit=0').json()['nodes'])
    assert client.post(uri + '/promote', json={'draft_id': 'draft:seed', 'version': 0}).status_code == 409
    raw = {'draft_id': 'draft:seed', 'version': 1}
    result = client.post(uri + '/promote', json=raw)
    assert result.status_code == 200, result.text
    promoted = result.json()
    assert client.post(uri + '/promote', json=raw).json() == promoted
    assert len(ideas.ideas()) == 1
    assert promoted['board']['root'] == 'idea:' + promoted['idea_id']
    assert not promoted['board']['drafts']
    assert client.request('DELETE', uri, json={'version': 1}).status_code == 409
    assert client.request('DELETE', uri, json={'version': 2}).status_code == 200
    assert len(ideas.ideas()) == 1


def test_local_connections_do_not_become_shared_on_promotion(ideas, authenticated_client):
    existing = ideas.save_idea(payload(), 'owner')
    shared = 'idea:' + existing['id']
    board = ideas.save_map(board_payload(members=[shared], edges=[{'source':'draft:seed','target':shared,'relation':'supports'}]))
    result = ideas.promote_draft(board['id'], 'draft:seed', 1, 'owner')
    assert result['board']['edges'][0]['source'] == 'idea:' + result['idea_id']
    assert ideas.links() == []
    assert ideas.map(board['id'])['version'] == 2
    edge = result['board']['edges'][0]
    uri = BASE + '/maps/' + board['id'] + '/promote-link'
    raw = {'version':2,'edge':edge}
    response = authenticated_client.post(uri,json=raw)
    assert response.status_code == 200, response.text
    assert authenticated_client.post(uri,json=raw).status_code == 200
    assert len(ideas.links()) == 1
    assert ideas.map(board['id'])['edges'] == []


def test_agent_context_and_proposals_preserve_local_scope(ideas, authenticated_client):
    from modules.hfl_corpus.ideas_brainstorm import snapshot
    board = ideas.save_map(board_payload(prompt='Develop a complete draft board'))
    context = snapshot(board['id'])['source']
    assert context['members'][0]['id'] == 'draft:seed'
    assert context['purpose'] == 'Compare improvements'
    uri = BASE + '/maps/' + board['id'] + '/accept-proposal'
    raw = {'request_id':str(uuid4()),'parents':['draft:seed'],'item':{'title':'Measure packing time','body':'Run a trial'}}
    response = authenticated_client.post(uri,json=raw)
    assert response.status_code == 200, response.text
    assert authenticated_client.post(uri,json=raw).status_code == 200
    saved = ideas.map(board['id'])
    assert len(saved['drafts']) == 2 and len(saved['edges']) == 1
    assert ideas.ideas() == [] and ideas.links() == []
    raw['parents'] = ['draft:missing']
    assert authenticated_client.post(uri,json=raw).status_code == 404


def test_board_creation_conflicting_retry_is_rejected(ideas, authenticated_client):
    raw = board_payload()
    assert authenticated_client.post(BASE + '/maps',json=raw).status_code == 200
    assert authenticated_client.post(BASE + '/maps',json=raw).status_code == 200
    assert authenticated_client.post(BASE + '/maps',json={**raw,'purpose':'Different'}).status_code == 409


def test_promotion_receipt_survives_removing_shared_member(ideas):
    board = ideas.save_map(board_payload())
    result = ideas.promote_draft(board['id'], 'draft:seed', 1, 'owner')
    ideas.save_map({'version':2,'members':[],'root':''}, board['id'])
    retry = ideas.promote_draft(board['id'], 'draft:seed', 1, 'owner')
    assert retry['idea_id'] == result['idea_id']
    assert retry['board']['members'] == []
    assert len(ideas.ideas()) == 1


def test_unlinked_goal_save_and_board_attachment_do_not_load_corpus(ideas, authenticated_client, monkeypatch):
    from modules.hfl_corpus import ideas_api
    def unavailable():
        raise AssertionError('Saving an unlinked Goal must not load the corpus graph')
    monkeypatch.setattr(ideas_api, 'catalogue', unavailable)
    client = authenticated_client
    raw = {'request_id':str(uuid4()),'title':'A local outcome','milestones':[{'id':'first','title':'First result','actions':[]}]}
    response = client.post(BASE + '/goals', json=raw)
    assert response.status_code == 200, response.text
    goal = response.json()['item']
    assert client.post(BASE + '/goals', json=raw).json()['item']['id'] == goal['id']
    assert client.patch(BASE + '/goals/' + goal['id'], json={'version':1,'status':'active'}).status_code == 200
    response = client.post(BASE + '/maps', json=board_payload(members=['goal:' + goal['id']],goal_id=goal['id']))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('changes', [
    {'purpose': ''}, {'root': []}, {'root':'missing'}, {'drafts':[{'id':'draft:x','title':''}]},
    {'edges':[{'source':'draft:seed','target':'missing'}]}, {'edges':[{'source':[],'target':'draft:seed'}]},
    {'positions':{'missing':{'x':1,'y':2}}}, {'goal_id':'unknown'},
])
def test_invalid_boards_are_rejected(ideas, authenticated_client, changes):
    response = authenticated_client.post(BASE + '/maps', json=board_payload(**changes))
    assert response.status_code == 422, response.text
    assert ideas.maps() == []


def test_legacy_map_defaults_and_conflict(ideas, authenticated_client):
    old = ideas.save_map({'request_id':str(uuid4()),'name':'Legacy','members':[], 'prompt':'Keep this'})
    read = ideas.map(old['id'])
    assert read['purpose'] == 'Legacy' and read['prompt'] == 'Keep this'
    assert read['version'] == 1 and read['drafts'] == []
    uri = BASE + '/maps/' + old['id']
    assert authenticated_client.patch(uri,json={'version':1,'purpose':'Updated'}).status_code == 200
    assert authenticated_client.patch(uri,json={'version':1,'purpose':'Stale'}).status_code == 409


def test_goal_milestones_and_shared_graph_links(ideas, authenticated_client):
    client = authenticated_client
    idea = ideas.save_idea(payload(), 'owner')
    node = 'idea:' + idea['id']
    raw = {'request_id':str(uuid4()),'title':'Pack in ten minutes','success_criteria':'Median under ten minutes',
           'linked_objects':[node], 'milestones':[{'id':'trial','title':'Trial validates improvement','status':'achieved'}]}
    response = client.post(BASE + '/goals',json=raw)
    assert response.status_code == 200, response.text
    goal = response.json()['item']
    assert client.post(BASE + '/goals',json=raw).json()['item']['id'] == goal['id']
    assert goal['status'] == 'proposed'
    graph = client.get('/api/hfl/entities/graph?limit=0').json()
    assert any(n['id'] == 'goal:' + goal['id'] for n in graph['nodes'])
    assert any(e['source'] == node and e['target'] == 'goal:' + goal['id'] for e in graph['edges'])
    uri = BASE + '/goals/' + goal['id']
    assert client.patch(uri,json={'version':1,'status':'active'}).status_code == 200
    assert client.patch(uri,json={'version':1,'status':'achieved'}).status_code == 409
    assert client.post(BASE + '/goals',json={**raw,'request_id':str(uuid4()),'linked_objects':['idea:missing']}).status_code == 404


def test_attach_choices_paging_permissions_and_saved_members(ideas, authenticated_client, monkeypatch):
    from modules.hfl_corpus import entities, ideas_api
    def forbidden(*args, **kwargs):
        raise AssertionError('Attachment must not build the full graph or fetch remote snapshot')
    monkeypatch.setattr(entities, 'graph', forbidden)
    monkeypatch.setattr(ideas_api, 'canonical_snapshot', forbidden)
    for index in range(55):
        ideas.save_idea(payload(title=f'Choice {index:02}'), 'owner')
    hidden = ideas.save_idea(payload(title='Private', source={'entry_id':'hidden','path':'private.md'}), 'owner')
    board = ideas.save_map(board_payload())
    url = BASE + '/maps/' + board['id']
    first = authenticated_client.get(url+'/attach-options').json()
    second = authenticated_client.get(url+'/attach-options?offset=50').json()
    assert len(first['nodes']) == 50 and first['has_more']
    assert not second['has_more']
    assert not {n['id'] for n in first['nodes']} & {n['id'] for n in second['nodes']}
    all_nodes = first['nodes'] + second['nodes']
    assert 'idea:'+hidden['id'] not in {n['id'] for n in all_nodes}
    assert all_nodes == sorted(all_nodes, key=lambda n:(n['updated_at'],n['id']), reverse=True)
    selected = first['nodes'][0]['id']
    response = authenticated_client.patch(url,json={'version':1,'members':[selected]})
    assert response.status_code == 200, response.text
    reopened = authenticated_client.get(url+'/attach-options').json()
    assert selected not in {n['id'] for n in reopened['nodes']}
    assert reopened['total'] == first['total'] - 1
    matches = authenticated_client.get(url+'/attach-options?query=Choice%2002').json()
    assert [n['label'] for n in matches['nodes']] == ['Choice 02']
    assert authenticated_client.patch(url,json={'version':2,'members':[selected,'idea:'+hidden['id']]}).status_code == 404
    assert authenticated_client.get(url+'/attach-options?offset=-1').status_code == 422


def test_attach_picker_loading_retry_and_paging_browser(ideas, authenticated_client, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    board = ideas.save_map(board_payload())
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width':1200,'height':900})
            pending = []
            def respond(route):
                r=route.request; url=urlparse(r.url)
                if url.path.endswith('/attach-options'):
                    pending.append(route)
                    return
                response=authenticated_client.request(r.method,url.path+('?' + url.query if url.query else ''),
                    content=r.post_data_buffer,headers={'content-type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,
                    headers={'content-type':response.headers.get('content-type','text/html')})
            page.route('https://attach.test/**',respond)
            page.goto('https://attach.test/hfl-corpus/graph?board='+board['id'])
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.get_by_role('button',name='Attach existing',exact=True).click()
            dialog=page.locator('.idea-dialog')
            expect(dialog.get_by_role('status')).to_have_text('Loading items…')
            expect(dialog.locator('.idea-picker-spinner')).to_be_visible()
            page.wait_for_timeout(100)
            pending.pop().fulfill(status=502,content_type='text/html',body='Unavailable')
            expect(dialog.get_by_role('button',name='Retry',exact=True)).to_be_visible()
            dialog.get_by_role('button',name='Retry',exact=True).click()
            page.wait_for_timeout(100)
            pending.pop().fulfill(json={'nodes':[{'id':'daily:2026-09-01','kind':'daily','label':'September'}], 'total':51,'has_more':True})
            expect(dialog.get_by_role('button',name='September · daily')).to_be_visible()
            height=dialog.bounding_box()['height']
            expect(dialog.locator('.idea-attach-entity')).to_have_text('daily')
            assert dialog.locator('.idea-attach-dot').evaluate('(n)=>getComputedStyle(n).backgroundColor')=='rgb(149, 167, 195)'
            page.screenshot(path=str(tmp_path/'attach-picker-loaded.png'))
            dialog.get_by_role('button',name='Next',exact=True).click()
            expect(dialog.locator('.idea-picker-loading')).to_be_visible()
            assert dialog.bounding_box()['height']==height
            page.wait_for_timeout(100)
            route=pending.pop(); assert 'offset=50' in route.request.url
            route.fulfill(json={'nodes':[], 'total':51,'has_more':False})
            expect(dialog.get_by_role('button',name='Previous',exact=True)).to_be_visible()
            assert dialog.bounding_box()['height']==height
            dialog.get_by_label('Search',exact=True).fill('missing')
            page.wait_for_timeout(350)
            route=pending.pop(); assert 'offset=0' in route.request.url and 'query=missing' in route.request.url
            route.fulfill(json={'nodes':[], 'total':0,'has_more':False})
            expect(dialog.get_by_text('No matching objects available to attach.')).to_be_visible()
            close=dialog.get_by_role('button',name='Close editor',exact=True)
            assert close.evaluate('(n)=>getComputedStyle(n).padding') == '0px'
            page.screenshot(path=str(tmp_path/'attach-picker.png'))
            close.click(); expect(dialog).to_have_count(0)
        finally:
            browser.close()


def test_board_agent_status_and_retry_browser(ideas, authenticated_client, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    board=ideas.save_map(board_payload())
    run={'id':'test-run','state':'queued','result':{}}
    with sync_playwright() as engine:
        browser=engine.chromium.launch(channel='chrome',headless=True)
        try:
            page=browser.new_page(viewport={'width':1200,'height':900})
            def respond(route):
                r=route.request;url=urlparse(r.url)
                if '/agent-bridge/' in url.path:
                    if url.path.endswith('/continue'):
                        run.update(state='queued',result={})
                    route.fulfill(json={'runs':[run]})
                    return
                response=authenticated_client.request(r.method,url.path+('?' + url.query if url.query else ''),content=r.post_data_buffer,headers={'content-type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/html')})
            page.route('https://agent-board.test/**',respond)
            page.goto('https://agent-board.test/hfl-corpus/graph?board='+board['id'])
            page.get_by_role('button',name='Ask agent',exact=True).click()
            dialog=page.locator('.board-agent-dialog')
            expect(dialog.get_by_role('heading',name='Agent board planning',exact=True)).to_be_visible()
            expect(dialog.get_by_role('status')).to_contain_text('Queued')
            expect(dialog.locator('.idea-picker-spinner')).to_be_visible()
            expect(dialog.get_by_role('button',name='Request suggestions')).not_to_be_visible()
            expect(dialog.get_by_role('button',name='Cancel run')).to_be_visible()
            page.screenshot(path=str(tmp_path/'board-agent-queued.png'))
            run.update(state='running')
            expect(dialog.get_by_role('status')).to_contain_text('Running',timeout=10000)
            run.update(state='failed',result={'summary':'The response format could not be read.'})
            expect(dialog.get_by_role('status')).to_contain_text('Could not finish',timeout=10000)
            expect(dialog.locator('.idea-picker-spinner')).to_have_count(0)
            reply=dialog.get_by_label('Retry instructions (optional)')
            reply.fill('Keep the plan concise')
            page.screenshot(path=str(tmp_path/'board-agent-failed.png'))
            dialog.get_by_role('button',name='Retry suggestions').click()
            expect(dialog.get_by_role('status')).to_contain_text('Queued')
        finally:
            browser.close()


def test_attach_entities_use_profile_updates_and_single_permitted_projection(ideas, authenticated_client, monkeypatch):
    from modules.hfl_corpus import entities
    from workflows.hfl.entity_store import get_store
    entity_store = get_store()
    entity_store.save_profile('people:recent', 'people', {'name':'Renamed person'})
    with entity_store.connection() as db:
        db.execute("UPDATE profiles SET updated='2026-09-21 12:00:00'")
    rows = [dict(id='visible',title='Entry',path='public.md',anchor='entry',text='Entry ID: visible',
                 source='manual-entry',date='2026-09-01',tags=[],mentions=[
                     dict(id='people:recent',label='Old name',kind='people'),
                     dict(id='tools:older',label='Older tool',kind='tools')])]
    calls = []
    def project():
        calls.append(True)
        return rows
    monkeypatch.setattr(entities, 'projection', project)
    monkeypatch.setattr(entities, 'current_entries', lambda: pytest.fail('Must reuse permitted projection'))
    board = ideas.save_map(board_payload())
    response = authenticated_client.get(BASE+'/maps/'+board['id']+'/attach-options')
    assert response.status_code == 200, response.text
    nodes = response.json()['nodes']
    assert len(calls) == 1
    person = next(n for n in nodes if n['id']=='people:recent')
    tool = next(n for n in nodes if n['id']=='tools:older')
    assert person['label'] == 'Renamed person'
    assert person['updated_at'] > tool['updated_at']
    assert nodes.index(person) < nodes.index(tool)


def test_delete_board_feedback_failure_and_activity_transition_browser(ideas, authenticated_client):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    board = ideas.save_map(board_payload())
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width':1200,'height':900})
            deletes, graphs = [], []
            def respond(route):
                r=route.request;url=urlparse(r.url)
                if r.method == 'DELETE':
                    deletes.append(route);return
                if url.path == '/api/hfl/entities/graph':
                    graphs.append(route);return
                response=authenticated_client.request(r.method,url.path+('?' + url.query if url.query else ''),
                    content=r.post_data_buffer,headers={'content-type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,
                    headers={'content-type':response.headers.get('content-type','text/html')})
            page.route('https://delete.test/**',respond)
            page.goto('https://delete.test/hfl-corpus/graph?board='+board['id'])
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.get_by_role('button',name='Delete',exact=True).click()
            dialog=page.locator('.idea-dialog')
            dialog.get_by_role('button',name='Delete board',exact=True).click()
            expect(dialog.get_by_role('status')).to_have_text('Deleting board…')
            expect(dialog.get_by_role('button',name='Close editor')).to_be_disabled()
            page.wait_for_timeout(100)
            deletes.pop().fulfill(status=503,json={'detail':'Try again'})
            expect(dialog.get_by_role('alert')).to_contain_text('Your board and pending edits are retained.')
            assert ideas.map(board['id'])['id'] == board['id']
            dialog.get_by_role('button',name='Delete board',exact=True).click()
            page.wait_for_timeout(100)
            route=deletes.pop()
            response=authenticated_client.request('DELETE',BASE+'/maps/'+board['id'],json=route.request.post_data_json)
            assert response.status_code == 200
            route.fulfill(status=response.status_code,json=response.json())
            expect(dialog).to_have_count(0)
            status=page.locator('.idea-map-status')
            expect(status).to_have_text('Board deleted · Loading All activity…')
            expect(page.locator('[data-board-id="'+board['id']+'"]')).to_have_count(0)
            assert 'board=' not in page.url
            page.wait_for_timeout(100)
            graphs.pop().fulfill(json={'nodes':[],'edges':[],'sources':[]})
            expect(status).to_have_text('Board deleted · All activity')
            expect(page.locator('#kg-workspace')).not_to_have_attribute('inert','')
        finally:
            browser.close()
