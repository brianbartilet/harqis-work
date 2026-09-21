"""Boards preserve speculative planning while Goals remain reusable outcomes."""
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas, BASE, payload


def board_payload(**changes):
    return {'request_id': str(uuid4()), 'name': 'Faster fulfillment', 'purpose': 'Compare improvements',
            'root': 'draft:seed', 'drafts': [{'id': 'draft:seed', 'title': 'Packing', 'body': 'Try batching'}], **changes}


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
            if width < 760: page.locator('.kg-boards summary').click()
            count = len(graph_requests)
            page.get_by_role('button',name='New board',exact=True).click()
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
