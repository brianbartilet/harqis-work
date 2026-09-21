import json
from uuid import uuid4

import pytest


BASE = '/hfl-corpus/timeline/ideas'


@pytest.fixture
def ideas(monkeypatch, tmp_path):
    from modules.hfl_corpus import timeline, entities
    from workflows.hfl.timeline_store import FollowUpStore
    from workflows.hfl.ideas_store import IdeasStore
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'entities.sqlite3'))
    followups = FollowUpStore(tmp_path / 'ideas.sqlite3')
    monkeypatch.setattr(timeline, 'store', lambda: followups)
    monkeypatch.setattr(entities, 'current_entries', lambda *a: [])
    monkeypatch.setattr(entities, 'projection', lambda *a: [])
    return IdeasStore(followups)


def payload(**changes):
    return {'request_id': str(uuid4()), 'title': 'Build a reading room', 'description': 'Make space to think',
            'body': '## Plan\nKeep **useful** books.', 'checklists': [{'id': 'list', 'title': 'Prepare', 'items': [{'id': 'task', 'text': 'Choose a shelf', 'done': True}]}], **changes}


def test_edit_restore_and_concurrent_changes(ideas, authenticated_client):
    client = authenticated_client
    raw = payload()
    response = client.post(BASE + '/objects', json=raw)
    assert response.status_code == 200, response.text
    item = response.json()['item']
    assert client.post(BASE + '/objects', json=raw).json()['item']['id'] == item['id']
    uri = BASE + '/objects/' + item['id']
    assert client.patch(uri, json={'version': 1, 'status': 'dismissed'}).status_code == 200
    assert client.patch(uri, json={'version': 1, 'title': 'Stale'}).status_code == 409
    assert client.patch(uri, json={'version': 2, 'status': 'suggested'}).status_code == 200
    assert ideas.idea(item['id'])['body'] == raw['description'] + '\n\n' + raw['body']
    assert '<h2>Plan</h2>' in client.get(uri).json()['body_html']


def test_conversion_copies_files_atomically_and_supports_multiple_actions(ideas, authenticated_client):
    client = authenticated_client
    item = ideas.save_idea(payload(), 'owner')
    uri = BASE + '/objects/' + item['id']
    uploaded = client.post(uri + '/attachments', files={'files': ('notes.md', b'# Research', 'text/markdown')})
    assert uploaded.status_code == 200, uploaded.text
    attachment = uploaded.json()['attachments'][0]
    draft = client.get(uri + '/conversion').json()
    assert not draft['item']['checklists'][0]['items'][0]['done']
    raw = {'request_id': str(uuid4()), 'idea_version': item['version'], 'item': draft['item'], 'attachments': [attachment['id']]}
    result = client.post(uri + '/convert', json=raw)
    assert result.status_code == 200, result.text
    action = result.json()['item']
    assert action['status'] == 'open' and action['agent_enabled'] is False
    assert client.post(uri + '/convert', json=raw).json()['item']['id'] == action['id']
    assert client.post(uri + '/convert', json={**raw, 'item': {**raw['item'], 'title': 'Changed retry'}}).status_code == 409
    from modules.hfl_corpus.attachments import source_store
    files, source = source_store('actionable', action['id'])
    copy = files.list(source)[0]
    assert copy['id'] != attachment['id'] and copy['digest'] == attachment['digest']
    client.delete(uri + '/attachments/' + attachment['id'])
    assert files.path(copy).read_bytes() == b'# Research'
    second_draft = client.get(uri + '/conversion').json()
    bad = {**raw, 'request_id': str(uuid4()), 'idea_version': second_draft['idea_version']}
    assert client.post(uri + '/convert', json=bad).status_code == 409
    assert len(ideas.followups.list()) == 1  # Attachment failure rolls back the action.
    bad['attachments'] = []
    result = client.post(uri + '/convert', json=bad)
    assert result.status_code == 200, result.text
    assert len(ideas.followups.list()) == 2
    assert ideas.idea(item['id'])['checklists'][0]['items'][0]['done']


def test_named_maps_keep_membership_and_layout_separate(ideas, authenticated_client):
    item = ideas.save_idea(payload(), 'owner')
    node = 'idea:' + item['id']
    a = ideas.save_map({'request_id': str(uuid4()), 'name': 'Room', 'members': [node], 'positions': {node: {'x': 12, 'y': 15}}})
    b = ideas.save_map({'request_id': str(uuid4()), 'name': 'Home', 'members': [node], 'positions': {node: {'x': 50, 'y': 75}}})
    response = authenticated_client.patch(BASE + '/maps/' + a['id'], json={'version': 1, 'members': [], 'positions': {}})
    assert response.status_code == 200, response.text
    assert ideas.map(b['id'])['positions'][node]['x'] == 50
    assert ideas.idea(item['id'])['title']
    assert authenticated_client.patch(BASE + '/maps/' + a['id'], json={'version': 1, 'name': 'Stale'}).status_code == 409


def test_checklist_item_conversion_preserves_provenance_and_independent_state(ideas, authenticated_client):
    client = authenticated_client
    raw = payload()
    raw['checklists'][0]['cover'] = True
    idea = ideas.save_idea(raw, 'owner')
    uri = BASE + '/objects/' + idea['id']
    draft = client.get(uri + '/conversion?checklist_id=list&item_id=task').json()
    assert draft['item']['title'] == 'Choose a shelf'
    assert draft['item']['body'] == raw['description'] + '\n\n' + raw['body']
    assert draft['item']['checklists'] == []
    request = {**draft, 'request_id': str(uuid4()), 'attachments': []}
    response = client.post(uri + '/convert', json=request)
    assert response.status_code == 200, response.text
    action = response.json()['item']
    assert client.post(uri + '/convert', json=request).json()['item']['id'] == action['id']
    assert client.post(uri + '/convert', json={**request, 'item_id': 'different'}).status_code == 409
    saved = client.get(uri).json()['item']
    assert saved['checklists'][0]['cover'] is True
    assert saved['checklists'][0]['items'][0]['done'] is True
    assert saved['item_actions'] == [{'idea_id': idea['id'], 'checklist_id': 'list', 'item_id': 'task', 'action_id': action['id']}]
    assert any(link['source'] == 'idea:' + idea['id'] and link['target'] == 'action:' + action['id'] for link in ideas.links())
    assert client.get(uri + '/conversion?checklist_id=list&item_id=removed').status_code == 409
    assert len(ideas.followups.list()) == 1


def test_legacy_checklist_cover_migration_is_additive(ideas):
    from workflows.hfl.object_content import migrate_content, content_fields
    action, _ = ideas.followups.create({'request_id': str(uuid4()), 'title': 'Legacy', 'expected_outcome': 'Done'}, actor='owner')
    legacy = {**action, 'checklists': payload()['checklists']}
    with ideas.followups.connect() as db:
        db.execute('UPDATE followups SET payload=? WHERE id=?', (json.dumps(legacy), action['id']))
        db.execute("DELETE FROM object_content_migrations WHERE name='followups:checklist-cover-v1'")
        migrate_content(db, 'followups')
        migrate_content(db, 'followups')
    saved = ideas.followups.get(action['id'])
    assert saved['version'] == action['version']
    assert saved['checklists'][0] == {**legacy['checklists'][0], 'cover': False}
    with pytest.raises(ValueError):
        content_fields({'checklists': [{**legacy['checklists'][0], 'cover': 'true'}]})


@pytest.mark.parametrize('table', ['followups', 'idea_edits', 'timeline_suggestions'])
def test_description_migration_preserves_content_and_history(ideas, table):
    from workflows.hfl.object_content import migrate_content, content_fields
    idea = ideas.save_idea(payload(), 'owner')
    action, _ = ideas.followups.create({'request_id': str(uuid4()), 'title': 'Legacy', 'expected_outcome': 'Done'}, actor='owner')
    record = action if table == 'followups' else idea
    legacy = {**record, 'description': 'd' * 3000, 'body': 'b' * 50000}
    with ideas.followups.connect() as db:
        history_before = [tuple(r) for r in db.execute('SELECT * FROM followup_history')]
        idea_history_before = [tuple(r) for r in db.execute('SELECT * FROM idea_history')]
        if table == 'timeline_suggestions':
            db.execute('INSERT INTO timeline_suggestions (id,status,payload,updated_at) VALUES (?,?,?,?)',
                       (record['id'], 'suggested', json.dumps(legacy), record['updated_at']))
        else:
            db.execute(f'UPDATE {table} SET payload=? WHERE id=?', (json.dumps(legacy), record['id']))
        db.execute('DELETE FROM object_content_migrations WHERE name=?', (table + ':markdown-description-v1',))
        migrate_content(db, table)
        migrate_content(db, table)
        saved = json.loads(db.execute(f'SELECT payload FROM {table} WHERE id=?', (record['id'],)).fetchone()['payload'])
        assert saved['body'] == legacy['description'] + '\n\n' + legacy['body']
        assert saved['description'] == ''
        assert saved['version'] == legacy['version']
        assert content_fields(saved)['body'] == saved['body']
        assert [tuple(r) for r in db.execute('SELECT * FROM followup_history')] == history_before
        assert [tuple(r) for r in db.execute('SELECT * FROM idea_history')] == idea_history_before


def test_description_consolidation_deduplicates_and_keeps_edits(ideas):
    item = ideas.save_idea(payload(description='Same', body='Same'), 'owner')
    assert item['body'] == 'Same' and item['description'] == ''
    updated = ideas.save_idea({'version': item['version'], 'body': 'Edited'}, 'owner', item['id'])
    assert updated['body'] == 'Edited' and updated['description'] == ''


def test_legacy_recommendation_remains_visible_as_markdown(ideas):
    from workflows.hfl.object_content import migrate_content
    with ideas.followups.connect() as db:
        db.execute('INSERT INTO timeline_suggestions (id,status,payload,updated_at) VALUES (?,?,?,?)',
                   ('legacy-recommendation', 'suggested', json.dumps({'title': 'Legacy', 'recommendation': 'Keep this context'}), '2026-09-20'))
        db.execute("DELETE FROM object_content_migrations WHERE name='timeline_suggestions:markdown-description-v1'")
        migrate_content(db, 'timeline_suggestions')
    assert ideas.idea('legacy-recommendation')['body'] == 'Keep this context'


def test_graph_links_dates_and_dismissed_ideas(ideas, authenticated_client):
    item = ideas.save_idea(payload(source_date='2025-01-02', status='dismissed'), 'owner')
    node = 'idea:' + item['id']
    response = authenticated_client.post(BASE + '/links', json={'source': 'daily:2025-01-02', 'target': node})
    assert response.status_code == 200, response.text
    graph = authenticated_client.get('/api/hfl/entities/graph?limit=0').json()
    assert next(n for n in graph['nodes'] if n['id'] == node)['status'] == 'dismissed'
    assert {'created-on', 'source-date'} <= {e['relation'] for e in graph['edges'] if e['source'] == node}
    assert authenticated_client.post(BASE + '/links', json={'source': 'entry:protected', 'target': node}).status_code == 404
    assert authenticated_client.request('DELETE', BASE + '/links', json={'source': 'daily:2025-01-02', 'target': node}).status_code == 200
    assert ideas.idea(item['id'])


def test_generated_refresh_preserves_owner_edits(ideas):
    with ideas.followups.connect() as db:
        db.execute('INSERT INTO timeline_suggestions VALUES (?,?,?,?,?)', ('suggestion-old', 'suggested', '', json.dumps({'title': 'Generated', 'id': 'suggestion-old'}), '2026-01-01T00:00:00+00:00'))
    edited = ideas.save_idea({'version': 0, 'title': 'Owner title', 'status': 'dismissed'}, 'owner', 'suggestion-old')
    with ideas.followups.connect() as db:
        db.execute('UPDATE timeline_suggestions SET payload=? WHERE id=?', (json.dumps({'title': 'Regenerated'}), 'suggestion-old'))
    assert ideas.idea('suggestion-old')['title'] == 'Owner title'
    assert ideas.idea('suggestion-old')['status'] == 'dismissed'
    assert edited['created_at'] == '2026-01-01T00:00:00+00:00'
    assert ideas.followups.suggestion('suggestion-old')['title'] == 'Owner title'
    with ideas.followups.connect() as db:
        db.execute("UPDATE timeline_suggestions SET status='adopted',followup_id='followup-test' WHERE id='suggestion-old'")
    assert ideas.idea('suggestion-old')['status'] == 'adopted'
    assert ideas.idea('suggestion-old')['followup_id'] == 'followup-test'


def test_protected_evidence_excluded(ideas, authenticated_client):
    ideas.save_idea(payload(source={'path': 'secret.md', 'entry_id': 'hfl-secret'}), 'owner')
    assert authenticated_client.get(BASE + '/snapshot').json()['ideas'] == []


def test_public_duplicate_entry_id_does_not_expose_private_source(ideas, authenticated_client, monkeypatch):
    from modules.hfl_corpus import entities
    ideas.save_idea(payload(source={'path': 'private.md', 'entry_id': 'hfl-duplicate'}), 'owner')
    monkeypatch.setattr(entities, 'current_entries', lambda: [{'id': 'hfl-duplicate', 'path': 'public.md', 'text': 'Entry ID: hfl-duplicate'}])
    assert authenticated_client.get(BASE + '/snapshot').json()['ideas'] == []


def test_context_keeps_chained_ideas_and_excludes_unrelated_intent():
    from modules.hfl_corpus.ideas_graph import extend
    base = {'nodes': [{'id': 'entry:visible', 'kind': 'entries', 'label': 'Visible'}], 'edges': []}
    data = {'ideas': [dict(id=i, title=i, status='suggested', created_at='2026-09-20T00:00:00+00:00') for i in ('root', 'child', 'outside')],
            'actions': [], 'topics': [], 'links': [
                {'source': 'entry:visible', 'target': 'idea:root', 'relation': 'related-to'},
                {'source': 'idea:root', 'target': 'idea:child', 'relation': 'related-to'},
                {'source': 'idea:outside', 'target': 'daily:2020-01-01', 'relation': 'source-date'}]}
    result = extend(base, data, context='selected-view', limit=0)
    ids = {n['id'] for n in result['nodes']}
    assert {'idea:root', 'idea:child'} <= ids
    assert 'idea:outside' not in ids and 'daily:2020-01-01' not in ids


def test_idea_commands_proxy_to_canonical_host(ideas, authenticated_client, monkeypatch):
    import httpx
    from types import SimpleNamespace
    from modules.hfl_corpus import timeline
    monkeypatch.delenv('HFL_TIMELINE_LOCAL_PREVIEW')
    monkeypatch.setattr(timeline, 'get_settings', lambda: SimpleNamespace(hfl_corpus_api_url='https://canonical.test', hfl_corpus_api_token='test-token'))
    calls = []
    class Remote:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return httpx.Response(200, json={'item': {'id': 'canonical-idea'}})
    monkeypatch.setattr(timeline.httpx, 'AsyncClient', Remote)
    response = authenticated_client.post(BASE + '/objects', json=payload())
    assert response.status_code == 200
    assert calls[0][1] == 'https://canonical.test/api/hfl/timeline/ideas/objects'
    assert calls[0][2]['headers']['Authorization'] == 'Bearer test-token'
    assert ideas.ideas() == []


@pytest.mark.parametrize('value', [[{'title': 'Tasks', 'items': [{'text': 'A', 'done': 'yes'}]}], [{'title': '', 'items': []}]])
def test_checklists_reject_invalid_values(ideas, value):
    with pytest.raises(ValueError):
        ideas.save_idea(payload(checklists=value), 'owner')


def test_brainstorm_requires_review_and_accepts_selected_proposal(ideas, authenticated_client, monkeypatch, tmp_path):
    from modules.hfl_corpus import agent_bridge
    from workflows.hfl.agent_bridge_store import AgentBridgeStore
    from modules.hfl_shares.security import make_csrf_token
    bridge = AgentBridgeStore(tmp_path / 'bridge.sqlite3')
    monkeypatch.setattr(agent_bridge, 'bridge_store', lambda: bridge)
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-worker')
    item = ideas.save_idea(payload(), 'owner')
    node = 'idea:' + item['id']
    mindmap = ideas.save_map({'request_id': str(uuid4()), 'name': 'Reading', 'members': [node], 'prompt': 'Suggest related ideas'})
    client = authenticated_client
    owner = {'X-CSRF-Token': make_csrf_token('frontend-test-user')}
    worker = {'Authorization': 'Bearer test-worker'}
    response = client.post('/hfl-corpus/agent-bridge/sources/mindmap/' + mindmap['id'] + '/run', headers=owner, json={'request_key': str(uuid4()), 'auto_complete': True})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['snapshot']['auto_complete'] is False
    claim = client.post('/api/hfl-agent/runs/' + run['id'] + '/claim', headers=worker, json={})
    assert claim.status_code == 200, claim.text
    run = claim.json()
    def report(kind, payload):
        return client.post('/api/hfl-agent/runs/' + run['id'] + '/events', headers=worker, json={'lease_token': run['lease_token'], 'event_key': kind, 'kind': kind, 'payload': payload})
    assert report('plan', {'summary': 'Explore useful branches.'}).status_code == 200
    proposals = [{'title': 'Lighting', 'description': 'A reading lamp', 'body': 'Try warm light.', 'parents': [node]}]
    result = report('succeeded', {'summary': 'One proposal ready.', 'complete': True, 'evidence': [node], 'ideas': proposals})
    assert result.status_code == 200, result.text
    assert result.json()['state'] == 'review'
    assert len(ideas.ideas()) == 1
    uri = '/hfl-corpus/agent-bridge/mindmaps/' + mindmap['id'] + '/accept-proposal'
    raw = {'run_id': run['id'], 'index': 0, 'item': {k: v for k, v in proposals[0].items() if k != 'parents'}}
    accepted = client.post(uri, headers=owner, json=raw)
    assert accepted.status_code == 200, accepted.text
    assert client.post(uri, headers=owner, json=raw).status_code == 200
    assert len(ideas.ideas()) == 1
    assert len(ideas.map(mindmap['id'])['members']) == 1
    assert len(ideas.map(mindmap['id'])['drafts']) == 1
    assert ideas.links() == []


@pytest.mark.parametrize('width', [390, 1280])
def test_browser_create_map_idea_checklist_and_conversion(ideas, authenticated_client, width, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        hold_graph = False
        pending_graph = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(intercept):
            request = intercept.request
            url = urlparse(request.url)
            if hold_graph and (url.path == '/api/hfl/entities/graph' or url.path.endswith('/goal-options')):
                pending_graph.append(intercept)
                return
            if url.hostname != 'ideas.test':
                intercept.abort()
                return
            response = authenticated_client.request(request.method, url.path + ('?' + url.query if url.query else ''), content=request.post_data_buffer,
                headers={k: v for k, v in request.headers.items() if k.lower() in {'content-type', 'x-csrf-token'}})
            intercept.fulfill(status=response.status_code, body=response.content, headers={'content-type': response.headers.get('content-type', 'text/html')})
        page.route('**/*', route)
        page.goto('https://ideas.test/hfl-corpus/ideas')
        guide_button = page.get_by_role('button', name='Board guide', exact=True)
        guide_button.click()
        guide = page.get_by_role('dialog', name='Board guide', exact=True)
        expect(guide).to_be_visible()
        expect(guide.get_by_role('heading', name='Where your work goes')).to_be_visible()
        expect(guide.locator('.board-guide-flow > li')).to_have_count(3)
        assert guide.evaluate('e => e.scrollWidth <= e.clientWidth + 1')
        guide.locator('.agenda-form-body').evaluate('e => e.scrollTop = 0')
        page.screenshot(path=str(tmp_path / ('board-guide-' + str(width) + '.png')))
        page.keyboard.press('Escape')
        expect(guide).to_have_count(0)
        expect(guide_button).to_be_focused()
        if width < 760:
            page.locator('.kg-boards [data-section=boards] > summary').click()
        page.locator('.board-add-menu').get_by_role('button', name='Add', exact=True).click()
        page.locator('.board-add-menu').get_by_role('button', name='Board', exact=True).click()
        modal = page.locator('.idea-dialog')
        modal.get_by_label('Board name').fill('Reading room')
        modal.get_by_label('What are you exploring or trying to achieve?').fill('Design a comfortable place to read')
        modal.get_by_role('button', name='Save board', exact=True).click()
        expect(modal).to_have_count(0)
        expect(page.locator('#kg-map-count')).to_contain_text('1 nodes')
        assert ideas.ideas() == []
        page.locator('#kg-list button').filter(has_text='Reading room').click()
        page.get_by_role('menuitem', name='Promote to shared Idea', exact=True).click()
        expect(page.locator('#kg-detail .idea-status-pill')).to_have_text('Suggested')
        page.get_by_role('menuitem', name='Edit idea / checklists', exact=True).click()
        modal.get_by_label('Idea', exact=True).fill('Warm lighting')
        description = '# Lighting\n## Requirements\n- Use **warm** light.\n- Compare bulbs\n    - Check brightness\n\n1. Choose a lamp\n2. Install the bulb'
        modal.get_by_label('Markdown description', exact=True).fill(description)
        modal.get_by_label('Markdown description', exact=True).press('Tab')
        preview = modal.locator('.markdown-inline-preview')
        expect(preview).to_be_visible()
        expect(preview.locator('ul').first).to_have_css('list-style-type', 'disc')
        expect(preview.locator('ul ul')).to_have_css('list-style-type', 'circle')
        expect(preview.locator('ol')).to_have_css('list-style-type', 'decimal')
        expect(preview.locator('li').first).to_have_css('display', 'list-item')
        assert preview.locator('h1').evaluate('e => parseFloat(getComputedStyle(e).fontSize)') > preview.locator('h2').evaluate('e => parseFloat(getComputedStyle(e).fontSize)')
        preview.click()
        expect(modal.locator('textarea[name=body]')).to_have_value(description)
        modal.get_by_role('button', name='Add checklist', exact=True).click()
        modal.get_by_role('button', name='Add item', exact=True).click()
        modal.get_by_label('Checklist item', exact=True).fill('Compare bulbs')
        modal.get_by_role('checkbox', name='Complete Compare bulbs').check()
        modal.get_by_role('checkbox', name='Checklist cover', exact=True).check()
        modal.locator('input[type=file]').set_input_files({'name':'lighting.txt','mimeType':'text/plain','buffer':b'Warm light reference'})
        modal.get_by_role('button', name='Save', exact=True).click()
        expect(modal).to_have_count(0)
        page.get_by_role('menuitem', name='Make actionable', exact=True).click()
        expect(modal.get_by_role('checkbox', name='Complete Compare bulbs')).not_to_be_checked()
        expect(modal.get_by_text('lighting.txt', exact=True)).to_be_visible()
        modal.locator('.action-details > summary').click()
        modal.get_by_label('Expected outcome').fill('A comfortable place to read')
        modal.get_by_role('button', name='Save', exact=True).click()
        expect(modal).to_have_count(0)
        assert len(ideas.followups.list()) == 1
        expect(page.locator('#kg-map-count')).to_contain_text('2 nodes')
        source_id = 'idea:' + ideas.ideas()[0]['id']
        action_id = 'action:' + ideas.followups.list()[0]['id']
        assert any(link['source'] == source_id and link['target'] == action_id and link['relation'] == 'develops-into' for link in ideas.links())
        page.wait_for_function('''([source, target]) => [...window.HflIdeas.maps.sharedEdges.values()].some(
            edge => edge.source === source && edge.target === target && edge.relation === 'develops-into'
        )''', arg=[source_id, action_id])
        expect(page.locator('#kg-map-count')).to_contain_text('1 links')
        hold_graph = True
        page.locator('.board-add-menu').get_by_role('button', name='Add', exact=True).click()
        page.locator('.board-add-menu').get_by_role('button', name='Goal', exact=True).click()
        expect(modal.get_by_label('Goal', exact=True)).to_be_visible(timeout=1000)
        expect(modal.get_by_role('button', name='Save Goal', exact=True)).to_be_enabled()
        expect(modal.get_by_text('Loading optional Idea and Action links…')).to_be_visible()
        modal.get_by_label('Goal', exact=True).fill('Read comfortably every evening')
        modal.get_by_label('Success criteria').fill('Read for 30 minutes without eye strain')
        modal.get_by_role('button', name='Add milestone', exact=True).click()
        modal.get_by_label('Milestone', exact=True).fill('Lighting trial is successful')
        hold_graph = False
        for pending in pending_graph:
            pending.abort()
        expect(modal.get_by_role('button', name='Retry loading links')).to_be_visible()
        modal.get_by_role('button', name='Save Goal', exact=True).click()
        expect(modal).to_have_count(0)
        expect(page.locator('#kg-map-count')).to_contain_text('3 nodes')
        page.locator('.board-controls').get_by_role('button', name='Add thought', exact=True).click()
        modal.get_by_label('Thought', exact=True).fill('Try an adjustable lamp')
        modal.get_by_role('button', name='Save thought', exact=True).click()
        expect(modal).to_have_count(0)
        expect(page.locator('#kg-map-count')).to_contain_text('4 nodes')
        assert page.evaluate('''() => {
            const points=Object.values(window.HflIdeas.maps.getPositions());
            return points.every((a,i)=>points.slice(i+1).every(b=>Math.hypot(a.x-b.x,a.y-b.y)>=85));
        }''')
        expect(page.locator('.idea-map-status')).to_have_text('Saved')
        page.reload()
        expect(page.locator('#kg-map-count')).to_contain_text('4 nodes')
        page.wait_for_function('''([source, target]) => [...window.HflIdeas.maps.sharedEdges.values()].some(
            edge => edge.source === source && edge.target === target && edge.relation === 'develops-into'
        )''', arg=[source_id, action_id])
        if width < 760:
            page.locator('.kg-boards [data-section=boards] > summary').click()
        expect(page.locator('.board-list button[aria-current=true]')).to_have_attribute('aria-label', 'Reading room')
        page.screenshot(path=str(tmp_path / ('boards-' + str(width) + '.png')), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.locator('#idea-map-tools').get_by_role('button', name='Explore Activity Graph', exact=True).click()
        expect(page.locator('.board-controls')).to_have_count(0)
        assert page.evaluate('window.HflIdeas.maps.current') is None
        assert not any(n['kind'] == 'drafts' for n in authenticated_client.get('/api/hfl/entities/graph?limit=0').json()['nodes'])
        page.goto('https://ideas.test/hfl-corpus/graph?map=' + ideas.maps()[0]['id'])
        expect(page.locator('#kg-map-count')).to_contain_text('4 nodes')
        assert not errors, errors
        browser.close()
