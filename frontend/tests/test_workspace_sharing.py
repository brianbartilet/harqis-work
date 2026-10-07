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
    expect(page.get_by_role('tab', name='Details and Filtering', exact=True)).to_have_attribute('aria-selected', 'true')
    expect(page.get_by_role('tab', name='Recipe', exact=True)).to_have_count(0)
    expect(page.get_by_role('tab', name='Filters', exact=True)).to_have_count(0)
    expect(page.locator('[data-share-secrets-status]')).to_have_count(0)
    assert page.locator('#description').evaluate('(el)=>el.closest(".field").nextElementSibling.matches("[data-filter-section]")')
    expect(page.locator('[data-source-selector]')).to_be_visible()
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
    expect(board_graph.locator('.share-graph-directory')).to_have_count(0)
    page.locator('.share-tabs').scroll_into_view_if_needed()
    board_graph.screenshot(path=str(tmp_path / 'sharing-boards.png'))
    page.get_by_role('tab', name='Entries', exact=True).click()
    expect(page.locator('.share-agent-test')).not_to_be_visible()
    expect(page.locator('[data-test-agent]')).not_to_be_visible()
    entry = page.locator('.share-entry-card').first
    entry.locator('summary').click()
    expect(entry.locator('.share-entry-content.markdown-body')).to_be_visible()
    expect(page.get_by_text('Scroll for more entries', exact=True)).to_have_count(0)
    entry.screenshot(path=str(tmp_path / 'sharing-entry.png'))
    page.get_by_role('tab', name='Details and Filtering', exact=True).click()
    expect(page.locator('[data-source-selector]')).to_be_visible()
    page.get_by_role('tab', name='Agent', exact=True).click()
    expect(page.locator('.share-agent-test')).to_be_visible()
    expect(page.locator('[data-test-question]')).to_be_visible()
    expect(page.locator('[data-test-agent]')).to_be_visible()
    page.get_by_role('tab', name='Details and Filtering', exact=True).click()
    page.locator('#name').fill('Workspace demo')
    page.locator('#recipient').fill('Reviewer')
    page.locator('#auth-mode').select_option('qr')
    page.get_by_role('button', name='Generate snapshot and QR', exact=True).click()
    expect(page.locator('body')).to_contain_text('Workspace demo', timeout=15000)
    from modules.hfl_shares.store import get_share_store
    grant = get_share_store().list_shares()[0]
    page.goto('https://editing.test/sharing/shares/' + grant.id + '/preview')
    page.get_by_text('Explore shared actions, ideas, boards, plans and graphs', exact=True).click()
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


def test_graph_context_does_not_publish_excluded_node_positions(context, sharing_corpus):
    snapshot = build_snapshot(recipe(activity={
        'excluded_ids':['action:a'],
        'graph_view':{'positions':{'action:a':{'x':10,'y':20}, 'idea:i':{'x':30,'y':40}}},
    }), (sharing_corpus,))
    assert snapshot.activity['graph']['view']['positions'] == {'idea:i':{'x':30,'y':40,'manual':False}}


@pytest.mark.parametrize('value', [
    {'viewport':{'x':0,'y':0,'zoom':0}},
    {'viewport':{'x':float('inf'),'y':0,'zoom':1}},
    {'positions':{'node':{'x':float('nan'),'y':0}}},
    {'animation_time':float('inf')},
])
def test_graph_context_rejects_invalid_coordinates(value):
    from modules.hfl_shares.activity_models import GraphView
    with pytest.raises(ValueError):
        GraphView.model_validate(value)


@pytest.mark.parametrize('width', [1440, 390])
def test_recipe_defaults_exclusions_and_graph_preferences(editor_page, context, sharing_corpus, width, tmp_path):
    import json
    from playwright.sync_api import expect
    from modules.profile.models import OwnerProfile
    from modules.profile.store import get_profile_store
    from modules.hfl_shares.store import get_share_store

    get_profile_store().save(OwnerProfile(first_name='Someone', nickname='Sami'))
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':1000})
    page.goto('https://editing.test/sharing')
    automatic = page.locator('[name="automatic_sections"]')
    assert automatic.evaluate_all('(items)=>items.length===5 && items.every(i=>i.checked && i.disabled)')
    assert page.locator('[name="activity_sections"]').evaluate_all('(items)=>items.length===6 && items.every(i=>i.checked)')
    freeze = page.locator('[type="checkbox"][name="freeze_snapshot"]')
    freeze.uncheck()
    assert automatic.evaluate_all('(items)=>items.every(i=>!i.disabled)')
    page.locator('[name="automatic_sections"][value="ideas"]').uncheck()
    freeze.check()
    assert page.locator('form[data-social-form]').evaluate('(f)=>new FormData(f).getAll("automatic_sections")') == ['entries','actions','boards','plans']

    page.get_by_role('tab', name='Details and Filtering', exact=True).click()
    page.locator('summary').filter(has_text='Tags, dates, and topic').click()
    expect(page.locator('#topic-help')).to_be_visible()
    expect(page.locator('#context-prompt-help')).to_be_visible()
    expect(page.locator('[data-field-help]')).to_have_count(0)
    panel = page.locator('[data-excluded-panel]')
    expect(panel).not_to_be_visible()
    page.get_by_role('tab', name='Actions and Ideas', exact=True).click()
    expect(page.get_by_label('Include actions', exact=True)).to_be_checked()
    expect(page.get_by_label('Include ideas', exact=True)).to_be_checked()
    expect(page.get_by_label('Include completed', exact=True)).not_to_be_checked()
    expect(page.get_by_label('Include dismissed', exact=True)).not_to_be_checked()
    page.locator('[data-share-object="action:a"]').uncheck()
    expect(panel).to_be_visible()
    expect(panel).to_have_attribute('open', '')
    expect(panel.get_by_role('heading', name='Actions and Ideas')).to_be_visible()
    expect(panel.locator('.excluded-item > span')).to_have_text('Approved action')
    expect(panel.get_by_role('button', name='Restore Approved action')).to_have_text('Restore')
    assert panel.evaluate('(el)=>!!el.closest("aside") && !el.closest("form")')
    assert panel.bounding_box()['y'] > page.locator('[data-generated-shares-panel]').bounding_box()['y']
    panel.screenshot(path=str(tmp_path / f'sharing-excluded-items-{width}.png'))
    panel.locator('summary').click()
    page.locator('[data-share-object="idea:i"]').uncheck()
    expect(panel).to_have_attribute('open', '')
    panel.get_by_role('button', name='Restore Approved action').click()
    panel.get_by_role('button', name='Restore Current idea').click()
    expect(panel).not_to_be_visible()

    page.get_by_role('tab', name='Agent', exact=True).click()
    expect(page.locator('[data-test-question]')).to_have_value('What is Sami currently working on?')
    page.get_by_role('tab', name='Graph', exact=True).click()
    expect(page.locator('[data-preview-tab="graph"] canvas')).to_be_visible()
    expect(page.locator('.share-graph-directory')).to_have_count(0)
    graph = page.locator('[data-preview-tab="graph"]')
    graph.get_by_label('Graph preset', exact=True).select_option('sources')
    graph.get_by_label('Graph animation', exact=True).select_option('drift')
    graph.get_by_role('button', name='actions', exact=True).click()
    expect(graph.get_by_role('button', name='actions', exact=True)).to_have_attribute('aria-pressed','false')
    expected = {'preset':'sources','animation':'drift','hidden_kinds':['actions']}
    current_view = json.loads(page.locator('[name="graph_view"]').input_value())
    assert {key:current_view[key] for key in expected} == expected
    graph.get_by_label('Graph animation', exact=True).select_option('off')
    expect(page.locator('[data-preview-status]')).not_to_be_visible()
    graph.locator('canvas').scroll_into_view_if_needed()
    page.wait_for_function('JSON.parse(document.querySelector("[name=graph_view]").value).viewport !== null')
    page.wait_for_timeout(200)
    before_zoom = json.loads(page.locator('[name="graph_view"]').input_value())['viewport']['zoom']
    graph.get_by_role('button', name='Zoom in', exact=True).click()
    page.wait_for_function('(zoom)=>JSON.parse(document.querySelector("[name=graph_view]").value).viewport.zoom > zoom', arg=before_zoom)
    page.wait_for_timeout(200)
    canvas = graph.locator('canvas')
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    before_pan = json.loads(page.locator('[name="graph_view"]').input_value())['viewport']
    page.mouse.move(box['x']+20, box['y']+box['height']-25)
    page.mouse.down()
    page.mouse.move(box['x']+65, box['y']+box['height']-55, steps=8)
    page.mouse.up()
    page.wait_for_function('(x)=>Math.abs(JSON.parse(document.querySelector("[name=graph_view]").value).viewport.x-x)>1', arg=before_pan['x'])
    # ForceGraph refreshes its pointer hit-test canvas at an 800ms interval.
    page.wait_for_timeout(900)
    context_before_drag = json.loads(page.locator('[name="graph_view"]').input_value())
    position = context_before_drag['positions']['sources:notes']
    viewport = context_before_drag['viewport']
    x = box['x'] + box['width']/2 + (position['x']-viewport['x'])*viewport['zoom']
    y = box['y'] + box['height']/2 + (position['y']-viewport['y'])*viewport['zoom']
    page.mouse.move(x,y)
    page.wait_for_timeout(100)
    page.mouse.down()
    page.mouse.move(x+25,y+30,steps=8)
    page.mouse.up()
    page.wait_for_function('JSON.parse(document.querySelector("[name=graph_view]").value).positions["sources:notes"].manual === true', timeout=3000)
    graph.get_by_label('Graph animation', exact=True).select_option('drift')
    captured = json.loads(page.locator('[name="graph_view"]').input_value())
    page.get_by_role('tab', name='Details and Filtering', exact=True).click()
    page.locator('#name').fill('Graph preferences')
    page.locator('#recipient').fill('Reviewer')
    page.get_by_role('button', name='Save recipe', exact=True).click()
    expect(page.locator('[name="configuration_id"]')).not_to_have_value('')
    saved = get_share_store().list_configurations()[0]
    saved_view = saved.activity['graph_view']
    assert {key:saved_view[key] for key in expected} == expected
    assert saved_view['positions'] == captured['positions']
    assert saved_view['viewport'] == captured['viewport']
    assert saved.activity['automatic'] == ['entries','actions','boards','plans']
    snapshot = build_snapshot(saved, (sharing_corpus,))
    assert snapshot.activity['graph']['view'] == saved_view
    assert any(n['kind']=='actions' for n in snapshot.activity['graph']['nodes'])
    page.get_by_role('tab', name='Graph', exact=True).click()
    expect(graph.get_by_label('Graph preset', exact=True)).to_have_value('sources')
    expect(graph.get_by_label('Graph animation', exact=True)).to_have_value('drift')
    expect(graph.get_by_role('button', name='actions', exact=True)).to_have_attribute('aria-pressed','false')
    expect(page.locator('[data-preview-status]')).not_to_be_visible()
    graph.locator('[data-shared-graph]').scroll_into_view_if_needed()
    # Allow the graph's initial 250ms camera fit to finish before visual QA.
    page.wait_for_timeout(500)
    restored = json.loads(page.locator('[name="graph_view"]').input_value())
    assert restored['positions'] == saved_view['positions']
    assert restored['viewport'] == pytest.approx(saved_view['viewport'])
    graph.locator('[data-shared-graph]').screenshot(path=str(tmp_path / f'sharing-graph-settings-{width}.png'))


def test_plans_workspace_exclusions_and_live_refresh(context, sharing_corpus):
    context['plans'] = [dict(id='1', title='Trip', category='Travel', start_date='2026-10-10',
                             end_date='2026-10-12', description='Visit friends', notes='Bring gifts',
                             workspace_ids=['work']),
                        dict(id='2', title='Private trip', category='Travel', workspace_ids=['other'])]
    cfg = recipe(live_updates=True, activity={'sections': ['plans']})
    initial = build_snapshot(cfg, (sharing_corpus,))
    assert [p['id'] for p in initial.activity['plans']] == ['plan:1']
    assert not initial.entries
    assert 'Bring gifts' in initial.activity_entries[0].text
    assert '2026-10-12' in initial.activity_entries[0].text
    assert 'Private trip' not in str(initial.to_record())
    live = live_configuration(cfg, initial)
    context['plans'].append(dict(id='3', title='New date', category='Events', workspace_ids=['work']))
    context['plans'][0]['notes'] = 'Updated notes'
    refreshed = build_snapshot(live, (sharing_corpus,))
    assert [p['id'] for p in refreshed.activity['plans']] == ['plan:1']
    assert refreshed.activity['plans'][0]['notes'] == 'Updated notes'
    automatic = replace(live, activity={**live.activity, 'automatic': ['plans'], 'excluded_ids': ['plan:1']})
    assert [p['id'] for p in build_snapshot(automatic, (sharing_corpus,)).activity['plans']] == ['plan:3']
    disabled = replace(cfg, activity={**cfg.activity, 'sections': ['entries']})
    assert 'Trip' not in str(build_snapshot(disabled, (sharing_corpus,)).to_record())


def test_plans_template_dates_and_safe_markdown():
    from modules.hfl_shares.router import templates
    rendered = templates.env.get_template('modules/hfl_shares/_plans.html').render(
        plans=[dict(id='plan:1', title='<script>bad</script>', category='Travel',
                    start_date='2026-10-10', end_date='2026-10-12',
                    description='Visit friends', notes='Bring gifts')], plans_editable=True)
    assert 'data-share-object="plan:1"' in rendered
    assert '2026-10-12' in rendered and 'Visit friends' in rendered and 'Bring gifts' in rendered
    assert '<script>bad</script>' not in rendered


def test_load_plans_inherits_category_and_omits_agent_fields(monkeypatch):
    from types import SimpleNamespace
    from modules.hfl_corpus import memory_pins
    from modules.hfl_shares.activity import load_plans
    pin = dict(id=7, category_id=1, title='Visit', start_date='2026-10-01', end_date='2026-10-02',
               prompt='Description', note='Notes', updated_at='2026-09-01', agent_enabled=True)
    monkeypatch.setattr(memory_pins, 'get_memory_pin_store', lambda: SimpleNamespace(snapshot=lambda: {
        'categories': [dict(id=1, name='Travel', color='#3b82f6', workspace_ids=['work'])],
        'ranges': [pin, {**pin, 'id': 8, 'category_id': 2}]}))
    plans = load_plans()
    assert len(plans) == 1
    assert plans[0]['workspace_ids'] == ['work']
    assert plans[0]['description'] == 'Description' and plans[0]['notes'] == 'Notes'
    assert 'agent_enabled' not in plans[0]


@pytest.mark.parametrize('width', [1440, 390])
def test_plans_tab_timeline(editor_page, context, width):
    from playwright.sync_api import expect
    context['plans'] = [dict(id='1', title='Visit Manila', category='Travel', start_date='2026-10-10',
                             end_date='2026-10-12', description='Meet friends', notes='Bring gifts')]
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto('https://editing.test/sharing')
    assert page.locator('[data-share-tab="plans"]').evaluate('(el)=>el.nextElementSibling.dataset.shareTab') == 'graph'
    page.get_by_role('tab', name='Plans', exact=True).click()
    panel = page.locator('[data-preview-tab="plans"]')
    expect(panel.get_by_text('Visit Manila', exact=True)).to_be_visible()
    expect(panel.get_by_text('Meet friends', exact=True)).to_be_visible()
    expect(panel.get_by_text('Bring gifts', exact=True)).to_be_visible()
    expect(panel.locator('time').last).to_have_text('2026-10-12')
    panel.locator('[data-share-object="plan:1"]').uncheck()
    expect(panel.get_by_text('No eligible pinned dates selected.')).to_be_visible()
