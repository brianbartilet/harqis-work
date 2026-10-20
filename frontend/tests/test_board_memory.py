"""Recall history is atomic with board edits and never waits for corpus delivery."""
import json
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas
from test_hfl_boards import board_payload


def memories(store):
    from workflows.hfl.persistence import EntryEnvelope
    with store.followups.connect() as db:
        return [EntryEnvelope.from_payload(json.loads(r['payload']))
                for r in db.execute('SELECT payload FROM board_memories ORDER BY rowid')]


def test_idea_and_checklist_memories_skip_retries_and_unrelated_edits(ideas):
    from test_hfl_ideas import payload
    raw = payload()
    idea = ideas.save_idea(raw, 'owner')
    ideas.save_idea(raw, 'owner')
    assert len(memories(ideas)) == 2
    idea = ideas.save_idea({'version': 1, 'status': 'dismissed'}, 'owner', idea['id'])
    assert len(memories(ideas)) == 2
    idea = ideas.save_idea({'version': 2, 'title': 'Revised idea'}, 'owner', idea['id'])
    assert len(memories(ideas)) == 3
    lists = idea['checklists']
    lists[0]['items'][0]['done'] = False
    ideas.save_idea({'version': 3, 'checklists': lists}, 'owner', idea['id'])
    entries = [e.entry for e in memories(ideas)]
    assert len(entries) == 4
    assert all(e.source == 'manual-entry' for e in entries)
    assert 'select=idea%3A' in entries[0].references[0]
    assert 'Completed: False' in entries[-1].what_happened
    from workflows.hfl.intent_reuse import list_graph
    nodes, _ = list_graph({'ideas': [idea]})
    thought = next(n for n in nodes if n['kind'] == 'thoughts')
    assert thought['id'] in entries[1].what_happened


def test_idea_memory_failure_rolls_back_and_stale_edit_has_no_memory(ideas, monkeypatch):
    from test_hfl_ideas import payload
    from workflows.hfl import board_memory
    from workflows.hfl.timeline_store import FollowUpConflict
    idea = ideas.save_idea(payload(), 'owner')
    with pytest.raises(FollowUpConflict):
        ideas.save_idea({'version': 0, 'title': 'Stale'}, 'owner', idea['id'])
    def fail(*args, **kwargs):
        raise OSError('Disk full')
    monkeypatch.setattr(board_memory, 'record_memory', fail)
    with pytest.raises(OSError):
        ideas.save_idea({'version': 1, 'title': 'Lost'}, 'owner', idea['id'])
    assert ideas.idea(idea['id'])['title'] == idea['title']
    assert len(memories(ideas)) == 2


def test_action_checklist_records_without_initializing_ideas_store(tmp_path):
    from workflows.hfl.timeline_store import FollowUpStore
    from test_hfl_ideas import payload
    store = FollowUpStore(tmp_path / 'actions.sqlite3')
    raw = payload(expected_outcome='A useful result')
    item, _ = store.create(raw, actor='owner')
    store.create(raw, actor='owner')
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM board_memories').fetchone()[0] == 1
    lists = item['checklists']
    lists[0]['items'][0]['text'] = 'Choose two shelves'
    store.update(item['id'], {'version': 1, 'checklists': lists}, actor='owner')
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM board_memories').fetchone()[0] == 2


def test_standalone_list_memories_and_replay(ideas, authenticated_client):
    from test_hfl_ideas import BASE, payload
    raw = {'request_id': str(uuid4()), 'checklist': payload()['checklists'][0]}
    response = authenticated_client.post(BASE + '/lists', json=raw)
    assert response.status_code == 200, response.text
    item = response.json()['item']
    assert authenticated_client.post(BASE + '/lists', json=raw).status_code == 200
    assert len(memories(ideas)) == 1
    item['checklist']['items'][0]['text'] = 'A revised thought'
    response = authenticated_client.patch(BASE + '/lists/' + item['id'],
        json={'version': item['version'], 'checklist': item['checklist']})
    assert response.status_code == 200, response.text
    assert len(memories(ideas)) == 2


def test_promoted_idea_has_one_memory_on_retry(ideas):
    board = ideas.save_map(board_payload())
    result = ideas.promote_draft(board['id'], 'draft:seed', board['version'], 'owner')
    ideas.promote_draft(board['id'], 'draft:seed', board['version'], 'owner')
    entries = [e.entry for e in memories(ideas)]
    assert len(entries) == 2
    assert 'idea:' + result['idea_id'] in entries[-1].what_happened


def test_thought_revisions_ignore_layout_and_retries(ideas):
    raw = board_payload()
    board = ideas.save_map(raw)
    ideas.save_map(raw)
    board = ideas.save_map({'version':board['version'], 'positions':{'draft:seed':{'x':2,'y':4}}}, board['id'])
    assert len(memories(ideas)) == 1
    board = ideas.save_map({'version':board['version'], 'drafts':[{'id':'draft:seed','title':'Packing','body':'New plan'}]}, board['id'])
    board = ideas.save_map({'version':board['version'], 'drafts':raw['drafts']}, board['id'])
    entries = [e.entry for e in memories(ideas)]
    assert len(entries) == len({e.entry_id for e in entries}) == 3
    assert all(e.source == 'manual-entry' for e in entries)
    assert 'Try batching' in entries[0].what_happened
    assert 'New plan' in entries[1].what_happened
    assert 'Try batching' in entries[2].what_happened
    assert f'board={board["id"]}' in entries[0].references[0]
    assert 'select=draft%3Aseed' in entries[0].references[0]


def test_goal_updates_are_new_memories_and_noops_are_not(ideas, monkeypatch):
    from workflows.hfl import board_store
    monkeypatch.setattr(board_store, 'isoformat', lambda: '2026-09-21T17:30:00+00:00')
    raw = {'request_id':str(uuid4()), 'title':'Recall plans'}
    goal = ideas.save_goal(raw, 'owner')
    ideas.save_goal(raw, 'owner')
    goal = ideas.save_goal({'version':1, 'title':'Recall plans'}, 'owner', goal['id'])
    assert len(memories(ideas)) == 1
    goal = ideas.save_goal({'version':2,'status':'achieved','progress_notes':'Shipped'}, 'owner', goal['id'])
    entries = [e.entry for e in memories(ideas)]
    assert len(entries) == 2
    assert entries[0].when.isoformat() == '2026-09-22T01:30:00'
    assert 'Status: achieved' in entries[1].what_happened
    assert 'Progress notes: Shipped' in entries[1].what_happened
    assert 'Updated' in entries[1].what_happened


def test_memory_failure_rolls_back_object_and_conflict_does_not_capture(ideas, monkeypatch):
    from workflows.hfl import board_memory
    from workflows.hfl.timeline_store import FollowUpConflict
    board = ideas.save_map(board_payload())
    with pytest.raises(FollowUpConflict):
        ideas.save_map({'version':0,'drafts':[{'id':'draft:seed','title':'Stale'}]}, board['id'])
    assert len(memories(ideas)) == 1
    def fail(*a, **kw):
        raise OSError('Disk full')
    monkeypatch.setattr(board_memory, 'record_memory', fail)
    with pytest.raises(OSError):
        ideas.save_map({'version':1,'drafts':[{'id':'draft:seed','title':'Lost'}]}, board['id'])
    assert ideas.map(board['id'])['drafts'][0]['title'] == 'Packing'
    assert len(memories(ideas)) == 1
    with pytest.raises(OSError):
        ideas.save_goal({'request_id':str(uuid4()),'title':'Lost'}, 'owner')
    assert ideas.goals() == []


def test_outbox_failure_and_restart_preserve_exact_snapshot(ideas, tmp_path, monkeypatch):
    from workflows.hfl import board_memory, persistence
    from workflows.hfl.ideas_store import IdeasStore
    ideas.save_map(board_payload())
    monkeypatch.setenv('HFL_OUTBOX_PATH', str(tmp_path / 'outbox'))
    save = persistence.save_to_outbox
    def fail(*a):
        raise OSError('Offline')
    monkeypatch.setattr(persistence, 'save_to_outbox', fail)
    assert board_memory.stage_pending_memories(ideas) == 0
    monkeypatch.setattr(persistence, 'save_to_outbox', save)
    restarted = IdeasStore(ideas.followups)
    assert board_memory.stage_pending_memories(restarted) == 1
    assert board_memory.stage_pending_memories(restarted) == 0
    files = list((tmp_path / 'outbox').glob('*.json'))
    assert len(files) == 1
    assert persistence.load_outbox(files[0]).to_payload() == memories(ideas)[0].to_payload()


def test_graph_memory_links_use_permitted_entry_ids_and_update_dates(ideas, monkeypatch):
    from modules.hfl_corpus import entities, ideas_api
    from modules.hfl_corpus.ideas_graph import extend
    from workflows.hfl import board_store
    monkeypatch.setattr(board_store, 'isoformat', lambda: '2026-09-01T01:00:00+00:00')
    goal = ideas.save_goal({'request_id':str(uuid4()),'title':'Recall'}, 'owner')
    monkeypatch.setattr(board_store, 'isoformat', lambda: '2026-09-22T01:00:00+00:00')
    ideas.save_goal({'version':1,'progress_notes':'Progress'}, 'owner', goal['id'])
    envelope = memories(ideas)[1]
    monkeypatch.setattr(entities, 'current_entries', lambda: [
        {'id':'permitted-projection-id','path':'2026-09-22.md','text':envelope.entry.to_markdown()}])
    snapshot = ideas_api.permitted_snapshot()
    assert len(snapshot['memories']) == 1
    base = {'nodes':[{'id':'entry:permitted-projection-id','kind':'entries','label':'Progress'}],'edges':[]}
    graph = extend(base, snapshot, since='2026-09-22', until='2026-09-22', limit=0)
    assert any(e['source']=='goal:'+goal['id'] and e['target']=='entry:permitted-projection-id'
               and e['relation']=='memory-entry' for e in graph['edges'])
    hidden = extend({'nodes':[],'edges':[]}, snapshot, since='2026-09-22', until='2026-09-22', limit=0)
    assert not any(n['id']=='goal:'+goal['id'] for n in hidden['nodes'])


def test_default_drain_uses_configured_database(ideas, tmp_path, monkeypatch):
    from workflows.hfl.board_memory import stage_pending_memories
    ideas.save_map(board_payload())
    monkeypatch.setenv('HFL_TIMELINE_STORE_PATH', str(ideas.path))
    monkeypatch.setenv('HFL_OUTBOX_PATH', str(tmp_path / 'outbox'))
    assert stage_pending_memories() == 1


def test_delivery_retries_keep_one_entry_identity(ideas, tmp_path, monkeypatch):
    from workflows.hfl import persistence, entity_merges, entity_events
    ideas.save_map(board_payload())
    monkeypatch.setenv('HFL_TIMELINE_STORE_PATH', str(ideas.path))
    monkeypatch.setenv('HFL_OUTBOX_PATH', str(tmp_path / 'outbox'))
    monkeypatch.setattr(entity_merges, 'flush_audits', lambda: None)
    monkeypatch.setattr(entity_events, 'dispatch_pending', lambda: None)
    monkeypatch.setattr(persistence, 'is_canonical_machine', lambda: True)
    attempts = []
    def deliver(envelope):
        attempts.append(envelope.entry.entry_id)
        if len(attempts) == 1:
            raise ConnectionError('Index offline')
    monkeypatch.setattr(persistence, 'persist_envelope', deliver)
    assert persistence.flush_outbox()['failed'] == 1
    # Simulate a crash after durable file write but before the DB handoff acknowledgement.
    with ideas.followups.connect() as db:
        db.execute('UPDATE board_memories SET staged=0')
    assert persistence.flush_outbox()['delivered'] == 1
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert persistence.flush_outbox()['found'] == 0


@pytest.mark.parametrize('kind', ['thought', 'goal'])
def test_memory_link_opens_selected_object_browser(ideas, authenticated_client, monkeypatch, kind):
    from urllib.parse import urlencode, urlparse
    from playwright.sync_api import sync_playwright, expect
    board = ideas.save_map(board_payload())
    params = {'board':board['id'], 'select':'draft:seed'}
    key = board['id']+'/draft:seed'
    edit_label = 'Edit thought'
    if kind == 'goal':
        from modules.hfl_corpus import entities
        goal = ideas.save_goal({'request_id':str(uuid4()),'title':'Recall'}, 'owner')
        key = 'goal:'+goal['id']
        params = {'select':key}
        edit_label = 'Edit Goal / milestones'
        crowded = [{'id':f'entry:{i}', 'kind':'entries', 'label':f'Entry {i}'} for i in range(150)]
        crowded.append({'id':key,'object_id':goal['id'],'kind':'goals','label':'Recall'})
        monkeypatch.setattr(entities, 'graph', lambda *a, **kw: {'nodes':crowded,'edges':[],'sources':[]})
    destination = '/hfl-corpus/graph?' + urlencode(params)
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def respond(route):
                r = route.request
                url = urlparse(r.url)
                if url.path == '/memory':
                    route.fulfill(body=f'<html><a href="{destination}">Open thought</a>'
                        '<script src="/static/js/activity-modals.js"></script></html>', content_type='text/html')
                    return
                response = authenticated_client.request(r.method, url.path + ('?' + url.query if url.query else ''),
                    content=r.post_data_buffer, headers={'content-type':'application/json'})
                route.fulfill(status=response.status_code, body=response.content,
                    headers={'content-type':response.headers.get('content-type','text/html')})
            page.route('https://memory.test/**', respond)
            page.goto('https://memory.test/memory')
            page.get_by_role('link', name='Open thought').click()
            frame = page.frame_locator('iframe')
            expect(frame.get_by_role('button', name=edit_label, exact=True)).to_be_visible()
            expect(frame.get_by_role('link', name='View memory history')).to_have_attribute(
                'href', '/hfl-corpus?' + urlencode({'q':key}))
            assert not errors
        finally:
            browser.close()
