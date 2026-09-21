"""Boards preserve speculative planning while Goals remain reusable outcomes."""
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas, BASE, payload


def board_payload(**changes):
    return {'request_id': str(uuid4()), 'name': 'Faster fulfillment', 'purpose': 'Compare improvements',
            'root': 'draft:seed', 'drafts': [{'id': 'draft:seed', 'title': 'Packing', 'body': 'Try batching'}], **changes}


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
