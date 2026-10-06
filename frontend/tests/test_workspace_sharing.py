"""Publication boundaries and hybrid refresh across workspace object types."""
from dataclasses import replace

import pytest

from modules.hfl_shares.models import ShareConfiguration, ScopeSnapshot
from modules.hfl_shares.scope import build_snapshot
from modules.hfl_shares.activity_models import live_configuration
from test_hfl_shares import sharing_corpus
from test_hfl_ideas import ideas
from test_action_editing import editor_page


def recipe(**values):
    activity = dict(version=1, sections=['entries', 'actions', 'ideas', 'boards', 'graph'], workspace_ids=['work'])
    activity.update(values.pop('activity', {}))
    return ShareConfiguration(id='', name='Workspace', recipient='Test', sources=('__all__',), activity=activity, **values)


@pytest.fixture
def context(monkeypatch):
    from modules.hfl_shares import activity
    data = {'actions': [dict(id='a', title='Approved action', status='open', workspace_ids=['work'], body='Next steps'),
                        dict(id='outside', title='Outside action', status='open', workspace_ids=['other']),
                        dict(id='secret', title='Secret-backed action', status='open', workspace_ids=['work'], source={'path':'private.md','entry_id':'secret'})],
            'ideas': [dict(id='i', title='Current idea', status='suggested', workspace_ids=['work'])],
            'maps': [dict(id='b', name='Workspace board', workspace_ids=['work'], members=['action:a','action:outside'],
                          drafts=[{'id':'draft:d','title':'Thought','body':'Plan'}], edges=[], goal_id='g')],
            'goals': [dict(id='g', title='Mapped goal', linked_objects=['action:secret'], body='Goal details')],
            'links': [{'source':'action:a','target':'action:secret','relation':'related-to'},
                      {'source':'action:a','target':'idea:i','relation':'related-to'}]}
    monkeypatch.setattr(activity, 'load_context', lambda: data)
    monkeypatch.setattr(activity, 'mentions_for_documents', lambda docs: [])
    return data


def test_workspace_board_and_goal_do_not_expand_scope(context, sharing_corpus):
    snapshot = build_snapshot(recipe(), (sharing_corpus,))
    serialized = str(snapshot.to_record())
    assert 'Outside action' not in serialized
    assert 'Secret-backed action' not in serialized
    assert 'Mapped goal' in serialized and 'Thought' in serialized
    assert {o['id'] for o in snapshot.activity['actions']} == {'action:a'}
    restored = ScopeSnapshot.from_record(snapshot.to_record())
    assert restored == snapshot
    assert len(restored.all_entries) > len(restored.entries)


def test_outside_members_opt_in_and_exclusions_win(context, sharing_corpus):
    cfg = recipe(activity={'outside_board_ids':['b']})
    snapshot = build_snapshot(cfg, (sharing_corpus,))
    assert {o['id'] for o in snapshot.activity['actions']} == {'action:a', 'action:outside'}
    cfg = replace(cfg, activity={**cfg.activity, 'excluded_ids':['action:outside','goal:g']})
    snapshot = build_snapshot(cfg, (sharing_corpus,))
    assert 'Outside action' not in str(snapshot.to_record())
    assert snapshot.activity['goals'] == []


def test_shared_board_keeps_only_approved_positions_and_sizes(context, sharing_corpus):
    context['maps'][0]['positions'] = {'action:a': {'x': 120, 'y': 30}, 'action:secret': {'x': 900, 'y': 0}}
    context['maps'][0]['node_sizes'] = {'action:a': 7, 'action:secret': 9}
    graph = build_snapshot(recipe(), (sharing_corpus,)).activity['boards'][0]['graph']
    assert graph['positions'] == {'action:a': {'x': 120, 'y': 30}}
    assert graph['node_sizes'] == {'action:a': 7}


def test_no_entry_share_does_not_leak_entry_labels(context, sharing_corpus):
    snapshot = build_snapshot(recipe(activity={'sections':['actions','boards','graph']}), (sharing_corpus,))
    assert not snapshot.entries
    assert snapshot.activity_entries
    assert 'Planned the Japan trip' not in str(snapshot.to_record())


def test_hybrid_refresh_pins_objects_and_admits_matches_per_section(context, sharing_corpus):
    cfg = recipe(live_updates=True, activity={'automatic':['ideas']})
    initial = build_snapshot(cfg, (sharing_corpus,))
    live = live_configuration(cfg, initial)
    context['actions'].append(dict(id='new', title='New action', workspace_ids=['work'], status='open'))
    context['ideas'].append(dict(id='new', title='New idea', workspace_ids=['work'], status='suggested'))
    context['actions'][0]['body'] = 'Updated approved action'
    refreshed = build_snapshot(live, (sharing_corpus,))
    assert 'New action' not in str(refreshed.to_record())
    assert 'New idea' in str(refreshed.to_record())
    assert 'Updated approved action' in str(refreshed.to_record())
    assert 'Updated approved action' not in str(initial.to_record())


def test_secret_objects_require_allow_flag_and_entry_permission(context, sharing_corpus):
    entry = replace(sharing_corpus.entries[0], secret=True, tags=('secrets',))
    document = replace(sharing_corpus, entries=(entry,))
    context['actions'][0]['source'] = {'path':document.relative_path,'entry_id':'hfl-share-test'}
    cfg = recipe(include_secrets=True)
    assert 'Approved action' not in str(build_snapshot(cfg, (document,)).to_record())
    snapshot = build_snapshot(cfg, (document,), allow_secrets=True)
    assert 'Approved action' in str(snapshot.to_record())


def test_browser_cannot_read_raw_sharing_context(authenticated_client):
    assert authenticated_client.get('/hfl-corpus/timeline/ideas/share-context').status_code == 403
    assert authenticated_client.get('/api/hfl/timeline/ideas/share-context').status_code == 401


def test_entry_only_recipes_do_not_load_intents(monkeypatch, sharing_corpus):
    from modules.hfl_shares import activity
    monkeypatch.setattr(activity, 'load_context', lambda: pytest.fail('Entries-only shares must not load intents'))
    assert build_snapshot(recipe(activity={'sections':['entries']}), (sharing_corpus,)).entries


def test_empty_sections_and_newly_protected_objects_are_removed(context, sharing_corpus):
    assert not build_snapshot(recipe(activity={'sections':[]}), (sharing_corpus,)).all_entries
    cfg = recipe(live_updates=True, activity={'sections':['actions']})
    initial = build_snapshot(cfg, (sharing_corpus,))
    context['actions'][0]['source'] = {'path':'private.md','entry_id':'secret'}
    refreshed = build_snapshot(live_configuration(cfg, initial), (sharing_corpus,))
    assert not refreshed.all_entries


def test_new_attachments_stay_disabled_on_live_refresh(context, sharing_corpus, monkeypatch):
    from modules.hfl_shares import activity_references
    files = [('first.txt', '{"id":"first"}')]
    monkeypatch.setattr(activity_references, 'references', lambda identity: files if identity == 'action:a' else [])
    cfg = recipe(live_updates=True, references_enabled=True, activity={'sections':['actions']})
    initial = build_snapshot(cfg, (sharing_corpus,))
    files.append(('second.txt', '{"id":"second"}'))
    refreshed = build_snapshot(live_configuration(cfg, initial), (sharing_corpus,), enabled_reference_ids=initial.enabled_reference_ids)
    refs = refreshed.activity_entries[0].references
    assert refs[0].enabled and not refs[1].enabled


def test_legacy_canonical_server_cannot_silently_drop_secrets(context, sharing_corpus):
    context['_secrets_supported'] = False
    with pytest.raises(ValueError, match='canonical API needs'):
        build_snapshot(recipe(include_secrets=True), (sharing_corpus,), allow_secrets=True)


def test_object_chat_citations_use_same_snapshot(context, sharing_corpus, monkeypatch):
    from modules.hfl_shares.agent import _context, _validated_answer
    snapshot = build_snapshot(recipe(activity={'sections':['actions']}), (sharing_corpus,))
    assert 'Approved action' in _context(snapshot)
    assert 'Secret-backed action' not in _context(snapshot)
    citation = snapshot.activity_entries[0].citation
    answer = 'Review [[Approved action|' + citation + ']].'
    assert _validated_answer(answer, snapshot) == answer
    assert 'enough information' in _validated_answer('Hidden [[secret|S999]].', snapshot)


def test_attachment_download_is_bound_to_captured_digest(context, sharing_corpus, ideas, authenticated_client):
    import asyncio
    import io
    import json
    from starlette.datastructures import UploadFile
    from fastapi import HTTPException
    from modules.hfl_corpus.attachments import source_store
    from modules.hfl_shares.activity_references import download
    files, source = source_store('actionable', 'a')
    asyncio.run(files.upload(source, [UploadFile(filename='brief.txt', file=io.BytesIO(b'approved attachment'))]))
    snapshot = build_snapshot(recipe(references_enabled=True, activity={'sections':['actions']}), (sharing_corpus,))
    reference = snapshot.activity_entries[0].references[0]
    assert download(reference).filename == 'brief.txt'
    target = json.loads(reference.target)
    with pytest.raises(HTTPException):
        download(replace(reference, target=json.dumps({**target, 'digest':'0' * 64})))
    path = '/api/hfl/timeline/ideas/share-context/attachments/actionable/a/' + target['id']
    assert authenticated_client.get(path).status_code == 401
    assert authenticated_client.get(path, headers={'Authorization':'Bearer frontend-test-hfl-api-token'}).content == b'approved attachment'
    assert authenticated_client.get(path.replace('/api/hfl/', '/hfl-corpus/')).status_code == 403


def test_legacy_database_adds_columns_before_owner_index(tmp_path):
    import sqlite3
    from modules.hfl_shares.store import ShareStore, _SCHEMA
    database = tmp_path / 'old-shares.sqlite3'
    old_schema = '\n'.join(line for line in _SCHEMA.splitlines() if not any(
        line.strip().startswith(field + ' ') for field in ('instant', 'live_updates', 'live_configuration', 'snapshot_entry_count')))
    with sqlite3.connect(database) as db:
        db.executescript(old_schema)
    store = ShareStore(database)
    with store._connect() as db:
        assert 'instant' in {row['name'] for row in db.execute('PRAGMA table_info(shares)')}
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='idx_shares_owner_list'").fetchone()
    assert store.list_shares() == []


def test_large_entries_preview_is_paged_and_retains_reference_exclusions(editor_page, sharing_corpus, monkeypatch):
    from playwright.sync_api import expect
    from modules.hfl_shares import router
    base = build_snapshot(recipe(references_enabled=True, activity={'sections':['entries']}), (sharing_corpus,))
    entries = tuple(replace(base.entries[0], id=f'entry-{i}', moment=f'Preview entry {i}',
                            text='Full entry body ' * 1000,
                            references=(replace(base.entries[0].references[0], id=f'reference-{i}'),))
                    for i in range(225))
    def snapshot(request, configuration, disabled_reference_ids, **kwargs):
        return replace(base, entries=tuple(replace(entry, references=tuple(
            replace(ref, enabled=ref.id not in disabled_reference_ids) for ref in entry.references
        )) for entry in entries))
    monkeypatch.setattr(router, '_build_preview_snapshot', snapshot)
    page, _ = editor_page
    page.goto('https://editing.test/sharing')
    page.get_by_role('tab', name='Entries', exact=True).click()
    scroller = page.locator('[data-entry-scroll]')
    expect(scroller.locator('[name="enabled_reference_ids"]')).to_have_count(50)
    page.locator('[value="reference-0"][name="enabled_reference_ids"]').uncheck()
    scroller.evaluate('(el) => {el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event("scroll"));}')
    expect(scroller.locator('[data-entry-page-items="2"]')).to_have_count(1)
    page.locator('[value="reference-50"][name="enabled_reference_ids"]').uncheck()
    scroller.evaluate('(el) => {el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event("scroll"));}')
    expect(scroller.locator('[data-entry-page-items="3"]')).to_have_count(1)
    expect(scroller.locator('[name="enabled_reference_ids"]')).to_have_count(150)
    expect(page.locator('[value="reference-0"][name="enabled_reference_ids"]')).not_to_be_checked()
    expect(page.locator('[value="reference-50"][name="enabled_reference_ids"]')).not_to_be_checked()
    scroller.evaluate('(el) => {el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event("scroll"));}')
    expect(scroller.locator('[data-entry-page-items="4"]')).to_have_count(1)
    expect(scroller.locator('[data-entry-page-items="1"]')).to_have_count(0)
    expect(scroller.locator('[name="enabled_reference_ids"]')).to_have_count(150)
    scroller.evaluate('(el) => {el.scrollTop=0;el.dispatchEvent(new Event("scroll"));}')
    expect(scroller.locator('[data-entry-page-items="1"]')).to_have_count(1)
    expect(page.locator('[value="reference-0"][name="enabled_reference_ids"]')).not_to_be_checked()
    expect(page.locator('[value="reference-50"][name="enabled_reference_ids"]')).not_to_be_checked()
    expect(page.get_by_role('button', name='Next entries')).to_have_count(0)



@pytest.mark.parametrize('width', [1440, 390])
def test_editor_tabs_selection_and_public_graph(editor_page, context, sharing_corpus, width, tmp_path):
    from playwright.sync_api import expect
    context['actions'][0]['body'] = '## Next steps\n\n- **Review** the plan\n- Confirm scope'
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':1000})
    page.goto('https://editing.test/sharing')
    expect(page.get_by_role('tab', name='Recipe', exact=True)).to_have_attribute('aria-selected', 'true')
    expect(page.locator('[data-preview-shell]')).not_to_be_visible()
    expect(page.locator('[data-test-agent]')).not_to_be_visible()
    assert page.locator('[data-share-tab="entries"]').evaluate('(el)=>getComputedStyle(el).cursor') == 'pointer'
    assert page.locator('[data-recipe-fields]').evaluate('(el)=>{const access=[...el.querySelectorAll("details")].find(e=>e.textContent.includes("Access, expiry"));return !!(access.compareDocumentPosition(el.querySelector("[name=freeze_snapshot]")) & Node.DOCUMENT_POSITION_FOLLOWING)}')

    page.get_by_role('tab', name='Actions and Ideas').click()
    page.locator('[name="activity_sections"][value="actions"]').check()
    expect(page.locator('[data-share-object="action:a"]')).to_be_visible(timeout=15000)
    card = page.locator('.share-object-card').filter(has=page.locator('[data-share-object="action:a"]'))
    expect(card.locator('.markdown-body h2')).to_have_text('Next steps')
    expect(card.locator('.markdown-body li')).to_have_count(2)
    page.locator('.share-tabs').scroll_into_view_if_needed()
    page.screenshot(path=str(tmp_path / 'sharing-actions.png'))
    page.locator('[name="activity_sections"][value="ideas"]').check()
    expect(page.locator('[data-share-object="idea:i"]')).to_be_visible()
    card.get_by_role('button', name='Connections', exact=True).click()
    expect(page.locator('.share-connections-dialog canvas')).to_be_visible()
    expect(page.locator('.share-connections-dialog')).to_contain_text('Approved action')
    expect(page.locator('.share-connections-dialog .share-graph-inspector h2')).to_have_text('Next steps')
    expect(page.locator('.share-connections-dialog').get_by_role('button', name='Add to a board')).to_have_count(0)
    page.screenshot(path=str(tmp_path / 'sharing-connections.png'))
    page.get_by_role('button', name='Close connections').click()
    page.locator('[data-share-object="action:a"]').uncheck()
    expect(page.get_by_role('button', name='Restore Approved action')).to_be_visible()
    page.get_by_role('button', name='Restore Approved action').click()
    expect(page.locator('[data-share-object="action:a"]')).to_be_visible()
    page.get_by_role('tab', name='Boards', exact=True).click()
    page.locator('[name="activity_sections"][value="boards"]').check()
    expect(page.locator('[data-outside-board="b"]')).to_be_visible()
    page.locator('[data-outside-board="b"]').check()
    expect(page.locator('[data-preview-tab="boards"] canvas')).to_be_visible()
    board_graph = page.locator('[data-preview-tab="boards"] [data-shared-graph]').first
    board_graph.locator('.share-graph-directory summary').click()
    board_graph.get_by_role('searchbox', name='Find a shared graph object').fill('Thought')
    expect(board_graph.locator('.share-graph-directory li')).to_have_count(1)
    board_graph.locator('.share-graph-directory li button').click()
    expect(board_graph.locator('.share-graph-selection')).to_contain_text('Thought')
    expect(board_graph.locator('.share-graph-selection')).to_contain_text('Plan')
    page.locator('.share-tabs').scroll_into_view_if_needed()
    board_graph.screenshot(path=str(tmp_path / 'sharing-boards.png'))
    page.get_by_role('tab', name='Entries', exact=True).click()
    entry = page.locator('.share-entry-card').first
    entry.locator('summary').click()
    expect(entry.locator('.share-entry-content.markdown-body')).to_be_visible()
    expect(page.get_by_text('Scroll for more entries', exact=True)).to_have_count(0)
    entry.screenshot(path=str(tmp_path / 'sharing-entry.png'))
    page.get_by_role('tab', name='Filters', exact=True).click()
    expect(page.locator('[data-source-selector]')).to_be_visible()
    page.get_by_role('tab', name='Recipe', exact=True).click()
    page.locator('#name').fill('Workspace demo')
    page.locator('#recipient').fill('Reviewer')
    page.locator('#auth-mode').select_option('qr')
    page.get_by_role('button', name='Generate snapshot and QR', exact=True).click()
    expect(page.locator('body')).to_contain_text('Workspace demo', timeout=15000)
    from modules.hfl_shares.store import get_share_store
    grant = get_share_store().list_shares()[0]
    page.goto('https://editing.test/sharing/shares/' + grant.id + '/preview')
    page.get_by_text('Explore shared actions, ideas, boards and graphs', exact=True).click()
    page.locator('.shared-activity-public summary').filter(has_text='Workspace board').click()
    expect(page.locator('.shared-activity-public canvas').first).to_be_visible()
    assert not page.locator('.shared-activity-public input').count()
    page.screenshot(path=str(tmp_path / 'workspace-share.png'), full_page=True)


def test_shared_graph_markdown_sanitizes_untrusted_content():
    from modules.hfl_shares.router import _graph_view
    graph = {'nodes': [{'id':'idea:i','body':'## Notes\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))'}], 'edges': []}
    rendered = _graph_view(graph)
    assert '<h2' in rendered['nodes'][0]['body_html']
    assert '<script' not in rendered['nodes'][0]['body_html']
    assert 'href="javascript:' not in rendered['nodes'][0]['body_html']
    assert 'body_html' not in graph['nodes'][0]
