"""Browser checks against isolated real APIs; no production actions are mutated."""
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas, BASE, payload


@pytest.fixture
def editor_page(ideas, authenticated_client, monkeypatch, tmp_path):
    from modules.hfl_corpus import corpus
    from playwright.sync_api import sync_playwright
    monkeypatch.setattr(corpus, 'resolve_corpus_root', lambda: tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(intercept):
            req = intercept.request
            url = urlparse(req.url)
            if url.hostname != 'editing.test':
                intercept.abort()
                return
            response = authenticated_client.request(req.method, url.path + ('?' + url.query if url.query else ''),
                content=req.post_data_buffer,
                headers={key: value for key, value in req.headers.items() if key.lower() in {'content-type', 'x-csrf-token'}})
            intercept.fulfill(status=response.status_code, body=response.content,
                headers={'content-type': response.headers.get('content-type', 'text/html')})

        page.route('**/*', route)
        yield page, authenticated_client
        page.screenshot(path=str(tmp_path / 'action-editing.png'))
        browser.close()
        assert errors == []


@pytest.mark.parametrize('query,expected', [
    ('scope={"any":[]}', 'All activity'),
    ('scope={"any":[{"q":"planning"}]}', 'Corpus filters'),
    ('views=missing', 'Unavailable workspace'),
])
def test_workspace_status_resolves_without_selection(editor_page, query, expected):
    from playwright.sync_api import expect
    page, _ = editor_page
    page.goto('https://editing.test/hfl-corpus/actions?' + query)
    expect(page.locator('[data-board-context]')).to_have_text(expected)


@pytest.mark.parametrize('width', [1440, 390])
def test_kanban_full_workspace_controls(editor_page, width, tmp_path):
    from playwright.sync_api import expect
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':1000})
    page.goto('https://editing.test/hfl-corpus/actions')
    menu = page.locator('[data-workspace-menu]')
    menu.locator(':scope > summary').click()
    for label in ('Save', 'New', 'Edit Views', 'Remove', 'Generate share recipe', 'Sharing preview', 'Visualize'):
        expect(menu.get_by_role('button', name=label, exact=True)).to_be_visible()
    panel = menu.locator('.workspace-menu-panel').bounding_box()
    assert panel['x'] >= 0 and panel['x'] + panel['width'] <= width
    assert panel['width'] >= 280
    page.screenshot(path=str(tmp_path / 'kanban-workspace-menu.png'))
    menu.get_by_role('button', name='New', exact=True).click()
    dialog = page.locator('[data-workspace-dialog]')
    dialog.get_by_label('Name', exact=True).fill('Kanban focus')
    dialog.locator('[data-workspace-confirm]').click()
    page.wait_for_url('**/hfl-corpus/actions?**')
    expect(page.locator('[data-board-context]')).to_contain_text('Kanban focus')
    menu.locator(':scope > summary').click()
    menu.get_by_role('button', name='Edit Views', exact=True).click()
    dialog.locator('[data-add-block]').click()
    dialog.locator('[data-workspace-confirm]').click()
    expect(dialog).not_to_be_visible()
    expect(page.locator('[data-view-loading]')).not_to_be_visible()
    menu.locator(':scope > summary').click()
    menu.get_by_role('button', name='Visualize', exact=True).click()
    expect(page.locator('#view-visualizer')).to_be_visible()
    page.locator('[data-visualize-close]').click()
    expect(menu.locator('[data-dynamic-toggle]')).to_be_enabled()
    menu.locator('[data-dynamic-toggle]').check()
    page.wait_for_url('**/hfl-corpus/actions?**dynamic=1**')
    menu.locator(':scope > summary').click()
    expect(menu.locator('[data-dynamic-toggle]')).to_be_checked()
    page.route('**/sharing/from-corpus?mode=preview', lambda route: route.fulfill(content_type='text/html', body='<p>Preview ready</p>'))
    menu.get_by_role('button', name='Sharing preview', exact=True).click()
    expect(page.locator('[data-corpus-share-dialog]')).to_contain_text('Preview ready')
    page.locator('[data-corpus-share-close]').click()
    menu.locator('[data-view-picker] > summary').click()
    menu.locator('[data-view-all]').click()
    expect(page.locator('[data-board-context]')).to_have_text('All activity')
    assert '/hfl-corpus/actions' in page.url
    page.route('**/sharing/from-corpus', lambda route: route.fulfill(content_type='text/html', body='<h1>Share recipe draft</h1>'))
    menu.locator(':scope > summary').click()
    menu.get_by_role('button', name='Generate share recipe', exact=True).click()
    page.wait_for_url('**/sharing/from-corpus')
    expect(page.get_by_role('heading', name='Share recipe draft')).to_be_visible()


def create_action(client):
    response = client.post('/hfl-corpus/timeline/items', json={
        'request_id': str(uuid4()), 'title': 'Editing test', 'expected_outcome': 'Verified UI',
        'agent_enabled': False, 'checklists': [
            {'id': 'one', 'title': 'First', 'cover': True, 'items': [
                {'id': 'z', 'text': 'Zulu', 'done': True}, {'id': 'a', 'text': 'Alpha', 'done': False}]},
            {'id': 'two', 'title': 'Second', 'items': []},
        ]})
    assert response.status_code == 201, response.text
    return response.json()['item']


def test_actions_page_autosave_refresh_sort_and_move(editor_page):
    from playwright.sync_api import expect
    page, client = editor_page
    item = create_action(client)
    page.goto('https://editing.test/hfl-corpus/actions')
    expect(page.locator('.agenda-card').first).to_be_visible()
    cover = page.locator('.followups-lanes .checklist-card-cover label')
    expect(cover.first).to_have_text('Alpha')
    page.locator('.followups-lanes').get_by_role('button', name='Edit', exact=True).click()
    form = page.locator('#followup-form')
    form.locator('[name=title]').fill('Autosaved title')
    expect(form.locator('.editor-save-status')).to_have_text('Saved')
    uri = '/hfl-corpus/timeline/items/' + item['id']
    assert client.get(uri).json()['item']['title'] == 'Autosaved title'
    page.reload()
    expect(page.locator('#followup-editor')).to_be_visible()
    expect(form.locator('[name=title]')).to_have_value('Autosaved title')
    expect(form.get_by_role('textbox', name='Checklist name').last).to_have_value('Agent Instructions')
    form.locator('[data-list-id=one]').get_by_role('button', name='Sort items A–Z', exact=True).click()
    expect(form.locator('.editor-save-status')).to_have_text('Saved')
    assert client.get(uri).json()['item']['checklists'][0]['items'][0]['id'] == 'a'
    row = form.locator('[data-item-id=a]')
    row.get_by_role('button', name='Move item to another checklist').click()
    page.mouse.click(2, 2)
    expect(page.locator('.checklist-move-dialog')).to_have_count(0)
    expect(page.locator('#followup-editor')).to_be_visible()
    row.get_by_role('button', name='Move item to another checklist').click()
    page.get_by_role('combobox', name='Move item to checklist').select_option('two')
    assert client.get(uri).json()['item']['checklists'][1]['items'] == []
    expect(page.locator('.checklist-move-dialog')).to_be_visible()
    page.locator('.checklist-move-dialog').get_by_role('button', name='Confirm', exact=True).click()
    expect(form.locator('.editor-save-status')).to_have_text('Saved')
    assert client.get(uri).json()['item']['checklists'][1]['items'][0]['id'] == 'a'
    form.locator('[data-list-id=two]').get_by_role('button', name='Move checklist up').click()
    expect(form.locator('.editor-save-status')).to_have_text('Saved')
    assert client.get(uri).json()['item']['checklists'][0]['id'] == 'two'
    form.get_by_role('button', name='Close follow-up editor').click()
    expect(page.locator('#followup-editor')).not_to_be_visible()
    page.wait_for_function("!new URLSearchParams(location.search).has('edit')")


@pytest.mark.parametrize('width', [390, 1280])
def test_copy_list_dialog_pagination_and_search(editor_page, ideas, tmp_path, width):
    from playwright.sync_api import expect
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 900})
    for index in range(12):
        ideas.save_idea(payload(title=f'Copy target {index}', description=f'Unique description {index}'), 'owner')
    page.goto('https://editing.test/hfl-corpus/actions')
    page.evaluate("window.HflCopyList({id:'source',title:'Source',items:[]})")
    picker = page.get_by_role('dialog', name='Copy list to action or idea')
    expect(picker.locator('.intent-copy-choice')).to_have_count(10)
    expect(picker.get_by_role('button', name='Previous', exact=True)).to_be_disabled()
    page.screenshot(path=str(tmp_path / f'copy-list-{width}.png'))
    picker.get_by_role('button', name='Next', exact=True).click()
    expect(picker.locator('.intent-copy-choice')).to_have_count(2)
    expect(picker.get_by_text('Page 2 of 2', exact=True)).to_be_visible()
    picker.get_by_role('searchbox').fill('Unique description 11')
    expect(picker.locator('.intent-copy-choice')).to_have_count(1)
    expect(picker.get_by_text('Page 1 of 1', exact=True)).to_be_visible()
    expect(picker.locator('.intent-copy-kind')).to_have_text('Idea')
    picker.get_by_role('button', name='Close copy list').click()
    expect(picker).to_have_count(0)


def test_conflict_retains_edits_and_close_offers_discard(editor_page):
    from playwright.sync_api import expect
    page, client = editor_page
    item = create_action(client)
    uri = '/hfl-corpus/timeline/items/' + item['id']
    page.goto('https://editing.test/hfl-corpus/actions?edit_kind=actionable&edit=' + item['id'])
    form = page.locator('#followup-form')
    expect(form.locator('[name=title]')).to_have_value('Editing test')
    client.patch(uri, json={'version': item['version'], 'title': 'Other session'})
    form.locator('[name=title]').fill('Unsaved conflict')
    expect(form.locator('.editor-save-status')).to_contain_text('Couldn’t save')
    expect(form.locator('[name=title]')).to_have_value('Unsaved conflict')
    page.keyboard.press('Escape')
    expect(page.get_by_role('button', name='Keep editing')).to_be_visible()
    page.get_by_role('button', name='Keep editing').click()
    expect(form.locator('[name=title]')).to_have_value('Unsaved conflict')
    page.keyboard.press('Escape')
    page.get_by_role('button', name='Discard').click()
    expect(page.locator('#followup-editor')).not_to_be_visible()
    assert client.get(uri).json()['item']['title'] == 'Other session'


def test_add_linked_checklist_thought_and_idea_autosave(editor_page, ideas):
    from playwright.sync_api import expect
    page, client = editor_page
    idea = ideas.save_idea(payload(), 'owner')
    board = ideas.save_map({'request_id': str(uuid4()), 'name': 'Destination', 'purpose': 'Test'})
    page.goto('https://editing.test/hfl-corpus/actions?edit_kind=idea&edit=' + idea['id'])
    form = page.locator('.idea-dialog form')
    expect(form.locator('[name=title]')).to_have_value(idea['title'])
    form.locator('[name=title]').fill('Updated idea')
    expect(form.locator('.editor-save-status')).to_have_text('Saved')
    assert ideas.idea(idea['id'])['title'] == 'Updated idea'
    form.get_by_role('button', name='Add checklist item to board').click()
    page.get_by_role('button', name='Destination', exact=True).click()
    expect(page.get_by_text('Added to Destination', exact=True)).to_be_visible()
    saved = ideas.map(board['id'])
    assert 'idea:' + idea['id'] in saved['members']
    assert saved['drafts'][0]['title'] == 'Choose a shelf'
    assert 'item=task' in saved['drafts'][0]['body']
    assert saved['edges'][0]['source'] == 'idea:' + idea['id']

    page.locator('.board-picker').get_by_role('button', name='Close editor', exact=True).click()
    form.get_by_role('button', name='Add checklist item to board').click()
    expect(page.get_by_text('Already added to this board', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='Destination', exact=True)).to_be_disabled()
    expect(page.get_by_role('link', name='Open board')).to_have_attribute('href', '/hfl-corpus/graph?board=' + board['id'])
    page.get_by_role('link', name='Create a new board and add checklist item', exact=True).click()
    create = page.locator('.idea-dialog').last
    create.locator('[name=name]').fill('New destination')
    create.locator('[name=purpose]').fill('A board created from the picker')
    create.get_by_role('button', name='Create board and add', exact=True).click()
    expect(page.get_by_text('Added to New destination', exact=True)).to_be_visible()
    new = next(b for b in ideas.maps() if b['name'] == 'New destination')
    assert new['drafts'][0]['title'] == 'Choose a shelf'
    assert 'idea:' + idea['id'] in new['members']


@pytest.mark.parametrize('tags', ['', '#work', '#moments #MOMENTS #work'])
def test_manual_entry_always_has_one_moments_tag(tags):
    from modules.hfl_corpus.entry_create import CreateEntryRequest, make_manual_envelope
    entry = make_manual_envelope(CreateEntryRequest(date='2026-01-01', time='12:00',
        moment='Manual entry', what_happened='A moment', tags=tags)).entry
    assert sum(t.casefold().lstrip('#') == 'moments' for t in entry.tags) == 1


@pytest.mark.parametrize('width', [390, 1280])
def test_drag_item_to_empty_list_and_guard_new_draft(editor_page, width):
    from playwright.sync_api import expect
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    item = create_action(client)
    page.goto('https://editing.test/hfl-corpus/actions?edit_kind=actionable&edit=' + item['id'])
    form = page.locator('#followup-form')
    row = form.locator('[data-item-id=a] .checklist-markdown')
    row.scroll_into_view_if_needed()
    start = row.bounding_box()
    target = form.locator('[data-list-id=two] .checklist-add-item')
    target.scroll_into_view_if_needed()
    # Both lists fit after scrolling the target into view.
    start = row.bounding_box()
    end = target.bounding_box()
    page.mouse.move(start['x']+start['width']/2, start['y']+start['height']/2)
    page.mouse.down()
    page.mouse.move(end['x']+end['width']/2, end['y']+end['height']/2, steps=15)
    page.mouse.up()
    expect(form.locator('.editor-save-status')).to_have_text('Saved')
    saved = client.get('/hfl-corpus/timeline/items/' + item['id']).json()['item']
    assert saved['checklists'][1]['items'][0]['id'] == 'a'
    form.get_by_role('button', name='Close follow-up editor').click()
    page.locator('[data-board-create-menu] > summary').click()
    page.locator('[data-board-create-action]').click()
    form.locator('[name=title]').fill('Uncreated draft')
    page.keyboard.press('Escape')
    page.get_by_role('button', name='Save and close').click()
    expect(page.locator('.editor-close-question [role=alert]')).to_contain_text('required fields')
    page.get_by_role('button', name='Discard').click()
    assert len(client.get('/hfl-corpus/timeline/items?include_closed=true').json()['items']) == 1


def test_graph_is_page_and_controls_stay_pinned(editor_page, ideas):
    from playwright.sync_api import expect
    page, client = editor_page
    for i in range(16):
        ideas.save_map({'request_id':str(uuid4()), 'name':f'Board {i}', 'purpose':'Test'})
    page.goto('https://editing.test/hfl-corpus/graph')
    expect(page.locator('#activity-standalone')).to_have_count(0)
    toolbar = page.locator('.board-toolbar')
    expect(toolbar).to_be_visible()
    before = toolbar.bounding_box()['y']
    page.locator('.kg-boards').evaluate('el=>el.scrollTop=300')
    assert abs(toolbar.bounding_box()['y']-before) < 2
    expect(page.locator('.graph-controls')).to_have_count(0)
    expect(page.locator('#kg-open-filters')).to_have_text('Filters')


def test_connections_is_always_available_and_adds_board(editor_page, ideas):
    from playwright.sync_api import expect
    page, client = editor_page
    action = create_action(client)
    board = ideas.save_map({'request_id': str(uuid4()), 'name': 'Connections destination', 'purpose': 'Related work'})
    page.goto('https://editing.test/hfl-corpus/actions')
    card = page.locator('[data-board-lanes] [data-followup-id="' + action['id'] + '"]')
    expect(card.get_by_role('button', name='Add to board', exact=True)).to_have_count(0)
    endpoint = '**/actions/' + action['id'] + '/connections'
    page.route(endpoint, lambda route: route.fulfill(json={'root': 'action:' + action['id'], 'nodes': [], 'edges': []}))
    card.get_by_role('button', name='Connections', exact=True).click()
    preview = page.locator('.action-connections-dialog')
    expect(preview.get_by_text('No connections yet', exact=True)).to_be_visible()
    page.unroute(endpoint)
    preview.get_by_role('button', name='Add to a board', exact=True).click()
    picker = page.locator('.board-picker')
    picker.get_by_role('button', name='Connections destination', exact=True).click()
    expect(picker.get_by_text('Added to Connections destination', exact=True)).to_be_visible()
    picker.get_by_role('button', name='Close editor', exact=True).click()
    expect(preview.locator('canvas')).to_be_visible()
    expect(preview.get_by_role('link', name='Connections destination', exact=True)).to_have_attribute('href', '/hfl-corpus/graph?board=' + board['id'])
    assert 'action:' + action['id'] in ideas.map(board['id'])['members']
