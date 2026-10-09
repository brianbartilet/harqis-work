"""Board fields are a bidirectional view of membership, with no implied edges."""
from uuid import uuid4
from datetime import date

import pytest
from test_hfl_ideas import ideas, BASE, payload


def board(ideas, name='Planning', **values):
    return ideas.save_map(dict(request_id=str(uuid4()), name=name, members=[], positions={}, **values))


@pytest.mark.parametrize('kind', ['idea', 'action'])
def test_membership_roundtrip_orphans_and_detach(ideas, kind):
    first, second = board(ideas), board(ideas, 'Second')
    create = (lambda raw: ideas.save_idea(raw, 'owner')) if kind == 'idea' else (lambda raw: ideas.followups.create(raw, actor='owner')[0])
    read = ideas.idea if kind == 'idea' else ideas.followups.get
    edit = (lambda i, raw: ideas.save_idea(raw, 'owner', i)) if kind == 'idea' else (lambda i, raw: ideas.followups.update(i, raw, actor='owner'))
    item = create(payload(board_ids=[first['id'], second['id'], first['id']]))
    node = kind + ':' + item['id']
    assert read(item['id'])['board_ids'] == sorted([first['id'], second['id']])
    assert ideas.map(first['id'])['members'] == [node]
    assert ideas.map(first['id'])['edges'] == []
    current = ideas.map(second['id'])
    ideas.save_map(dict(version=current['version'], members=[]), second['id'])
    assert read(item['id'])['board_ids'] == [first['id']]
    # Unrelated edits never restore stale stored associations.
    edit(item['id'], dict(version=item['version'], title='Updated'))
    assert read(item['id'])['board_ids'] == [first['id']]
    edit(item['id'], dict(version=item['version'] + 1, board_ids=[]))
    assert ideas.map(first['id'])['members'] == []
    assert read(item['id'])['board_ids'] == []


def test_inactive_removed_and_invalid_boards_are_atomic(ideas):
    active = board(ideas)
    item = ideas.save_idea(payload(board_ids=[active['id']]), 'owner')
    saved = ideas.map(active['id'])
    ideas.save_map(dict(version=saved['version'], active=False), saved['id'])
    changed = ideas.save_idea(dict(version=1, board_ids=[], title='Retained'), 'owner', item['id'])
    assert changed['board_ids'] == [active['id']]
    for invalid in ([active['id']], ['removed'], 'bad', [None]):
        with pytest.raises(ValueError):
            ideas.save_idea(payload(board_ids=invalid), 'owner')
    assert len(ideas.ideas()) == 1
    saved = ideas.map(active['id'])
    ideas.delete_board(saved['id'], saved['version'])
    assert ideas.idea(item['id'])['board_ids'] == []


def test_conversion_inherits_boards_and_graph_membership(ideas, authenticated_client):
    selected = board(ideas)
    idea = ideas.save_idea(payload(board_ids=[selected['id']]), 'owner')
    draft = authenticated_client.get(BASE + '/objects/' + idea['id'] + '/conversion').json()
    assert draft['item']['board_ids'] == [selected['id']]
    response = authenticated_client.post(BASE + '/objects/' + idea['id'] + '/convert', json=dict(
        request_id=str(uuid4()), idea_version=idea['version'], item={'title': 'Act'}, attachments=[]))
    assert response.status_code == 200, response.text
    action = response.json()['item']
    assert action['board_ids'] == [selected['id']]
    saved = ideas.map(selected['id'])
    assert set(saved['members']) == {'action:' + action['id']}
    assert ideas.ideas() == []
    assert ideas.idea(idea['id'])['promoted_to'] == action['id']
    assert saved['edges'] == []
    from modules.hfl_corpus.entities import graph
    assert any(e['source'] == 'board:' + selected['id'] and e['target'] == 'action:' + action['id']
               for e in graph(limit=0)['edges'])


@pytest.mark.parametrize('via_board', [False, True])
def test_added_actions_enter_review_above_manual_order(ideas, via_board):
    selected = board(ideas)
    first, second = [ideas.followups.create(payload(title=title), actor='owner')[0] for title in ['First', 'Second']]
    assert ideas.followups.board_order()[second['id']] < ideas.followups.board_order()[first['id']]
    ideas.followups.reorder_board('open', [{'id': first['id'], 'version': 1}, {'id': second['id'], 'version': 1}])
    action = ideas.followups.update(second['id'], {'version': 1, 'status': 'in_progress'}, actor='owner')
    if via_board:
        ideas.save_map({'version': selected['version'], 'members': ['action:' + action['id']]}, selected['id'])
    else:
        ideas.followups.update(action['id'], {'version': action['version'], 'board_ids': [selected['id']]}, actor='owner')
    saved = ideas.followups.get(action['id'])
    assert saved['status'] == 'open'
    assert saved['board_ids'] == [selected['id']]
    positions = ideas.followups.board_order()
    assert positions[second['id']] < positions[first['id']]
    ideas.followups.update(saved['id'], {'version': saved['version'], 'title': 'Edited'}, actor='owner')
    assert ideas.followups.board_order() == positions


def test_promotion_replaces_inactive_board_layout_and_preserves_history(ideas, authenticated_client):
    idea = ideas.save_idea(payload(), 'owner')
    node = 'idea:' + idea['id']
    selected = ideas.save_map(dict(request_id=str(uuid4()), name='Archived',
                                   members=[node], root=node, positions={node: {'x': 12, 'y': 45}}))
    selected = ideas.save_map({'version': selected['version'], 'active': False}, selected['id'])
    response = authenticated_client.post(BASE + '/objects/' + idea['id'] + '/convert', json=dict(
        request_id=str(uuid4()), idea_version=idea['version'], item={'title': 'Act'}, attachments=[]))
    assert response.status_code == 200, response.text
    action = response.json()['item']
    saved = ideas.map(selected['id'])
    target = 'action:' + action['id']
    assert saved['members'] == [target]
    assert saved['root'] == target
    assert saved['positions'] == {target: {'x': 12, 'y': 45}}
    assert action['board_ids'] == [selected['id']]
    assert ideas.snapshot()['ideas'] == []
    assert ideas.idea(idea['id'])['promoted_to'] == action['id']
    assert any(link['source'] == node and link['target'] == target for link in ideas.links())


def test_complete_board_context_excludes_inactive_and_protected_objects(ideas, monkeypatch):
    from modules.hfl_corpus import entities
    from modules.hfl_corpus.intent_board_context import context
    idea = ideas.save_idea(payload(), 'owner')
    node = 'idea:' + idea['id']
    selected = board(ideas)
    ideas.save_map(dict(version=1, members=[node, 'entry:protected']), selected['id'])
    board(ideas, 'Inactive', active=False)
    monkeypatch.setattr(entities, 'graph', lambda **kw: {'nodes': [dict(id=node, kind='ideas', body='x' * 7000)], 'edges': []})
    result = context()
    assert [b['id'] for b in result] == [selected['id']]
    assert [m['id'] for m in result[0]['members']] == [node]
    assert len(result[0]['members'][0]['body']) == 7000


def test_generated_idea_associations_are_additive_and_actions_inherit(ideas):
    first, second = board(ideas), board(ideas, 'Related')
    inactive = board(ideas, 'Inactive', active=False)
    day = '2026-10-01'
    run = ideas.followups.claim_period(day, day)
    ideas.followups.start_period(day, day, run)
    candidate = dict(category='recommendations', title='Generated idea', confidence='high',
                     expected_outcome='Deliver', source={'entry_id': 'e', 'path': 'note.md'},
                     evidence=[{'entry_id': 'e'}], board_ids=[first['id'], inactive['id'], 'missing'])
    ideas.followups.save_suggestions(day, day, run, [candidate], {}, state='running')
    item = ideas.ideas()[0]
    assert item['board_ids'] == [first['id']]
    ideas.followups.save_suggestions(day, day, run, [{**candidate, 'board_ids': [second['id']]}], {}, state='running')
    assert ideas.idea(item['id'])['board_ids'] == sorted([first['id'], second['id']])
    snapshot = ideas.followups.automation_snapshot()
    result = ideas.followups.apply_auto_decisions([ideas.idea(item['id'])], [dict(suggestion_id=item['id'], decision='create',
        confidence='high', completion_check='clear', reason='Evidence supports this action')], snapshot['digest'], date(2026, 10, 1))
    assert result['created'] == 1
    assert ideas.followups.get(result['created_ids'][0])['board_ids'] == sorted([first['id'], second['id']])


@pytest.mark.parametrize('width', [390, 1280])
@pytest.mark.parametrize('kind', ['idea', 'actionable'])
def test_browser_board_checkbox_field(ideas, authenticated_client, width, kind, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    older, newer = board(ideas, 'Older board'), board(ideas, 'Latest board')
    board(ideas, 'Inactive board', active=False)
    # Timestamps are intentionally distinct, rather than relying on clock resolution.
    import json
    with ideas.followups.connect() as db:
        older['updated_at'] = '2026-01-01T00:00:00+00:00'
        db.execute('UPDATE idea_maps SET payload=? WHERE id=?', (json.dumps(older), older['id']))
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(intercept):
            request = intercept.request
            url = urlparse(request.url)
            response = authenticated_client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                content=request.post_data_buffer, headers={k: v for k, v in request.headers.items() if k.lower() in {'content-type', 'x-csrf-token'}})
            intercept.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get('content-type', 'text/html'))
        page.route('https://boards-field.test/**', route)
        try:
            page.goto('https://boards-field.test/hfl-corpus')
            page.evaluate('(kind) => window.HflIdeas.openEditor(kind)', kind)
            dialog = page.locator('.idea-dialog')
            dialog.locator('[name=title]').fill('Board selection test')
            picker = dialog.locator('[data-intent-boards]')
            picker.get_by_label('Boards', exact=True).click()
            expect(picker.locator('label')).to_have_text(['Latest board', 'Older board'])
            expect(picker.get_by_text('Inactive board')).to_have_count(0)
            picker.get_by_label('Latest board', exact=True).check()
            picker.get_by_label('Older board', exact=True).check()
            assert picker.evaluate('(el)=>el.getBoundingClientRect().top > el.parentElement.querySelector("details").getBoundingClientRect().top')
            page.screenshot(path=str(tmp_path / f'boards-{kind}-{width}.png'))
            # Submit while the dropdown is still open: neither selection may be lost.
            dialog.get_by_role('button', name='Create', exact=True).click()
            expect(dialog).to_have_count(0)
            item = ideas.ideas()[0] if kind == 'idea' else ideas.followups.list()[0]
            assert item['board_ids'] == sorted([older['id'], newer['id']])
            prefix = 'idea:' if kind == 'idea' else 'action:'
            assert all(ideas.map(b['id'])['members'] == [prefix + item['id']] for b in [older, newer])
            page.evaluate('([kind,item]) => window.HflIdeas.openEditor(kind,item)', [kind, item])
            picker = dialog.locator('[data-intent-boards]')
            picker.get_by_label('Boards', exact=True).click()
            expect(picker.get_by_label('Latest board', exact=True)).to_be_checked()
            expect(picker.get_by_label('Older board', exact=True)).to_be_checked()
            picker.get_by_label('Older board', exact=True).uncheck()
            picker.get_by_label('Boards', exact=True).click()
            expect(dialog.locator('.editor-save-status')).to_have_text('Saved')
            read = ideas.idea if kind == 'idea' else ideas.followups.get
            assert read(item['id'])['board_ids'] == [newer['id']]
            # A title edit must not undo membership added from another board editor.
            external = board(ideas, 'Externally attached')
            ideas.save_map(dict(version=external['version'], members=[prefix + item['id']]), external['id'])
            dialog.locator('[name=title]').fill('Renamed without changing boards')
            expect(dialog.locator('.editor-save-status')).to_have_text('Saved')
            assert read(item['id'])['board_ids'] == sorted([newer['id'], external['id']])
            assert not errors, errors
        finally:
            page.close()
            browser.close()
