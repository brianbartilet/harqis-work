"""Browser checks against isolated real APIs; no production actions are mutated."""
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas, BASE, payload
from test_corpus_workspaces import workspace_corpus


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
    ('views=missing', 'Unavailable Space'),
])
def test_workspace_status_resolves_without_selection(editor_page, query, expected):
    from playwright.sync_api import expect
    page, _ = editor_page
    page.goto('https://editing.test/hfl-corpus/actions?' + query)
    expect(page.locator('[data-board-context]')).to_have_text(expected)


@pytest.mark.parametrize('width', [1440, 390])
def test_kanban_full_workspace_controls(editor_page, workspace_corpus, width, tmp_path):
    from playwright.sync_api import expect
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':1000})
    page.goto('https://editing.test/hfl-corpus/actions')
    menu = page.locator('[data-workspace-menu]')
    if not menu.evaluate('(element) => element.open'):
        menu.locator(':scope > summary').click()
    for label in ('Generate share recipe', 'Sharing preview', 'Visualize'):
        expect(menu.get_by_role('button', name=label, exact=True)).to_be_visible()
    panel = menu.locator('.workspace-menu-panel').bounding_box()
    assert panel['x'] >= 0 and panel['x'] + panel['width'] <= width
    assert panel['width'] >= 280
    page.screenshot(path=str(tmp_path / 'kanban-workspace-menu.png'))
    menu.get_by_role('link', name='Manage Spaces').click()
    page.locator('#space-destination').select_option('new')
    page.locator('#space-apply-draft').click()
    page.get_by_label('Name', exact=True).fill('Kanban focus')
    page.locator('[data-add-block]').click()
    page.get_by_role('button', name='Save Space', exact=True).click()
    expect(page.locator('#space-status')).to_contain_text('Space saved')
    page.goto('https://editing.test/hfl-corpus/actions')
    expect(page.locator('[data-active-view-name]')).to_have_text('Kanban focus')
    expect(page.locator('[data-dynamic-badge]')).to_have_text('Dynamic OFF')
    expect(page.locator('[data-active-view-modified]')).to_have_text('Saved')
    if not menu.evaluate('(element) => element.open'):
        menu.locator(':scope > summary').click()
    menu.get_by_role('button', name='Visualize', exact=True).click()
    expect(page.locator('#view-visualizer')).to_be_visible()
    page.locator('[data-visualize-close]').click()
    expect(menu.locator('[data-dynamic-toggle]')).to_be_enabled()
    menu.locator('[data-dynamic-toggle]').check()
    page.wait_for_url('**/hfl-corpus/actions?**dynamic=1**')
    expect(page.locator('[data-dynamic-badge]')).to_have_text('Dynamic ON')
    if not menu.evaluate('(element) => element.open'):
        menu.locator(':scope > summary').click()
    expect(menu.locator('[data-dynamic-toggle]')).to_be_checked()
    page.route('**/sharing/from-corpus?mode=preview', lambda route: route.fulfill(content_type='text/html', body='<p>Preview ready</p>'))
    menu.get_by_role('button', name='Sharing preview', exact=True).click()
    expect(page.locator('[data-corpus-share-dialog]')).to_contain_text('Preview ready')
    page.locator('[data-corpus-share-close]').click()
    menu.locator('[data-view-picker] > summary').click()
    menu.locator('[data-view-all]').click()
    page.wait_for_url('**dynamic=0**')
    expect(page.locator('[data-dynamic-badge]')).to_have_text('Dynamic OFF')
    expect(page.locator('[data-view-loading]')).not_to_be_visible()
    expect(page.locator('[data-active-view-name]')).to_have_text('All activity')
    assert '/hfl-corpus/actions' in page.url
    page.route('**/sharing/from-corpus', lambda route: route.fulfill(content_type='text/html', body='<h1>Share recipe draft</h1>'))
    if not menu.evaluate('(element) => element.open'):
        menu.locator(':scope > summary').click()
    menu.get_by_role('button', name='Generate share recipe', exact=True).click()
    page.wait_for_url('**/sharing/from-corpus')
    expect(page.get_by_role('heading', name='Share recipe draft')).to_be_visible()


@pytest.mark.parametrize('source_state', ['available', 'missing', 'manual'])
def test_idea_card_date_and_source(editor_page, source_state):
    from playwright.sync_api import expect
    from urllib.parse import parse_qs
    page, _ = editor_page
    item = {'id': str(uuid4()), 'title': 'Traceable idea', 'status': 'suggested',
            'origin': 'manual' if source_state == 'manual' else 'agent',
            'created_at': '2026-10-05T18:30:00Z'}
    if source_state != 'manual':
        item.update(generated_at='2026-10-04T18:30:00Z',
                    source={'path': '2026/10/example & notes.md', 'entry_id': 'entry-123', 'title': 'Source note'},
                    evidence_available=source_state == 'available')
    page.route('**/ideas/reuse/board-ideas?*', lambda route: route.fulfill(json={'items': [item]}))
    page.goto('https://editing.test/hfl-corpus/actions')
    page.get_by_role('button', name='Show ideas', exact=True).click()
    card = page.locator('[data-idea-id="' + item['id'] + '"]')
    first_pill = card.locator('.agenda-card-meta > :first-child')
    expect(first_pill).to_have_text('6 Oct 2026' if source_state == 'manual' else '5 Oct 2026')
    expect(first_pill.locator('time')).to_have_attribute('datetime', item.get('generated_at', item['created_at']))
    if source_state == 'available':
        link = card.get_by_role('link', name='Open HFL entry ↗')
        expect(link).to_be_visible()
        url = urlparse(link.get_attribute('href'))
        assert url.path == '/hfl-corpus/timeline/evidence'
        assert parse_qs(url.query) == {'path': [item['source']['path']], 'entry_id': ['entry-123']}
    else:
        expect(card.get_by_role('link', name='Open HFL entry ↗')).to_have_count(0)
        if source_state == 'missing':
            expect(card.locator('[aria-disabled="true"]')).to_have_text('HFL entry unavailable')


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


def test_planned_categories_workspace_filter_and_editor(editor_page, workspace_corpus, tmp_path):
    from datetime import date
    from modules.hfl_shares.security import make_csrf_token
    from playwright.sync_api import expect
    page, client = editor_page
    csrf = make_csrf_token('frontend-test-user')
    views = [client.post('/hfl-corpus/workspace-views', headers={'X-CSRF-Token': csrf},
             json={'name': name, 'state': {}}).json() for name in ['Work', 'Personal']]
    def save(**values):
        response = client.post('/hfl-corpus/memory-pins', json={'csrf': csrf, **values})
        assert response.status_code == 200, response.text
        return response.json()
    cat = save(action='save_category', name='Shared plans', color='#3b82f6',
               workspace_ids=[view['id'] for view in views])['categories'][0]
    today = date.today().isoformat()
    save(action='save_range', category_id=cat['id'], title='Shared trip', start_date=today, end_date=today)
    save(action='save_range', category_id=cat['id'], title='NTU AI Certification', start_date=today, end_date=today,
         note='Long event notes ' * 80)
    other = save(action='save_category', name='Unassigned plans', color='#f59e0b')['categories'][-1]
    save(action='save_range', category_id=other['id'], title='Unassigned trip', start_date=today, end_date=today)
    for view in views:
        page.goto('https://editing.test/hfl-corpus?workspace=' + view['id'])
        if not page.locator('[data-activity-body]').is_visible():
            page.locator('[data-activity-toggle]').click()
        expect(page.locator('[data-activity-pin-list]')).to_contain_text('Shared trip')
        expect(page.locator('[data-activity-pin-list]')).not_to_contain_text('Unassigned trip')
    cell = page.locator(f'[data-activity-day="{today}"]')
    cell.hover()
    tooltip = page.locator('#activity-cell-tooltip')
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text('NTU AI Certification')
    expect(tooltip).to_contain_text('Shared trip')
    page.evaluate('(day)=>window.HflActivityIndicators.setActions({[day]:{planned:["one"],actions:[],dot_status:"open"}})', today)
    expect(tooltip).to_contain_text('NTU AI Certification')
    expect(tooltip).to_contain_text('1 actions')
    assert tooltip.evaluate('(el)=>el.scrollHeight>el.clientHeight')
    bounds = tooltip.bounding_box()
    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 1280
    page.keyboard.press('Escape')
    expect(tooltip).not_to_be_visible()
    page.locator('[data-activity-pin-list]').get_by_role('button', name='Edit', exact=True).first.click()
    host = page.locator('[data-memory-category-workspaces]')
    host.locator('summary').click()
    expect(host.get_by_label('Work', exact=True)).to_be_checked()
    expect(host.get_by_label('Personal', exact=True)).to_be_checked()
    page.screenshot(path=str(tmp_path / 'planned-category-workspaces.png'))
    host.get_by_label('Personal', exact=True).uncheck()
    page.locator('[data-memory-category-save]').click()
    expect(page.locator('[data-memory-dialog]')).not_to_be_visible()
    expect(page.locator('[data-activity-pin-list]')).not_to_contain_text('Shared trip')
    expect(page.locator(f'[data-activity-day="{today}"]')).to_have_attribute('data-pinned', 'false')
    page.goto('https://editing.test/hfl-corpus?views=')
    if not page.locator('[data-activity-body]').is_visible():
        page.locator('[data-activity-toggle]').click()
    expect(page.locator('[data-activity-pin-list]')).to_contain_text('Shared trip')
    expect(page.locator('[data-activity-pin-list]')).to_contain_text('Unassigned trip')
    page.locator('[data-memory-category-new]').click()
    page.locator('[data-memory-category-name]').fill('All workspace plans')
    host = page.locator('[data-memory-category-workspaces]')
    expect(host.locator('summary')).to_have_text('All workspaces')
    host.locator('summary').click()
    expect(host.get_by_label('Work', exact=True)).to_be_checked()
    expect(host.get_by_label('Personal', exact=True)).to_be_checked()
    host.get_by_role('button', name='No Space', exact=True).click()
    expect(host.locator('summary')).to_have_text('No Space')
    host.locator('summary').click()
    host.get_by_role('button', name='Select all', exact=True).click()
    expect(host.get_by_label('Work', exact=True)).to_be_checked()
    expect(host.get_by_label('Personal', exact=True)).to_be_checked()
    with page.expect_response(lambda response: response.url.endswith('/memory-pins') and response.request.method == 'POST') as saved:
        page.locator('[data-memory-category-save]').click()
    category = next(item for item in saved.value.json()['categories'] if item['name'] == 'All workspace plans')
    assert set(category['workspace_ids']) == {view['id'] for view in views}


@pytest.mark.parametrize('editor', ['timeline', 'idea', 'actionable'])
@pytest.mark.parametrize('count', [0, 1, 2])
def test_new_objects_inherit_selected_workspaces(editor_page, workspace_corpus, editor, count):
    from urllib.parse import urlencode
    from playwright.sync_api import expect
    from modules.hfl_corpus import workspace_views
    page, client = editor_page
    views = [workspace_views.save(workspace_views.WorkspaceWrite(name=name, state={})) for name in ('Work', 'Home')]
    selected = sorted(view['id'] for view in views[:count])
    query = {'reset': '1'} if not selected else {'workspace' if count == 1 else 'views': ','.join(selected)}
    page.goto('https://editing.test/hfl-corpus/actions?' + urlencode(query))
    page.wait_for_function('window.hflActions && window.HflIdeas')
    if editor == 'timeline':
        page.evaluate('window.hflActions.openEditor()')
        form = page.locator('#followup-form')
    else:
        page.evaluate('(kind) => window.HflIdeas.openEditor(kind)', editor)
        form = page.locator('.idea-dialog:visible form')
    expect(form.locator('[data-intent-fields] > input[name=workspace_ids]')).to_have_count(count)
    assert sorted(form.evaluate('(form) => new FormData(form).getAll("workspace_ids")')) == selected
    form.locator('[name=title]').fill('Inherited workspace ' + editor)
    if editor != 'idea':
        form.locator('[name=expected_outcome]').evaluate('(input) => { input.value="Done"; input.dispatchEvent(new Event("input", {bubbles:true})); }')
    save_path = BASE + '/objects' if editor == 'idea' else '/hfl-corpus/timeline/items'
    with page.expect_response(lambda response: response.request.method == 'POST' and urlparse(response.url).path == save_path) as saved:
        form.locator('[type=submit]').click()
    assert saved.value.status == (200 if editor == 'idea' else 201)
    endpoint = BASE + '/reuse/board-ideas' if editor == 'idea' else '/hfl-corpus/timeline/items'
    item = next(item for item in client.get(endpoint).json()['items'] if item['title'] == 'Inherited workspace ' + editor)
    assert item['workspace_ids'] == selected


def test_checklist_action_is_atomic_and_retryable(ideas, authenticated_client):
    client = authenticated_client
    parent = create_action(client)
    uri = '/hfl-corpus/timeline/items/' + parent['id']
    raw = {'request_id': str(uuid4()), 'version': parent['version'], 'checklist_id': 'one', 'item_id': 'a',
           'item': {'title': 'Alpha action', 'expected_outcome': 'Alpha'}}
    stale = client.post(uri + '/checklist-action', json={**raw, 'version': 0})
    assert stale.status_code == 409
    assert len(ideas.followups.list()) == 1
    assert not client.get(uri).json()['item']['checklists'][0]['items'][1]['done']
    saved = client.post(uri + '/checklist-action', json=raw)
    assert saved.status_code == 200, saved.text
    assert saved.json()['parent']['checklists'][0]['items'][1]['done']
    assert not saved.json()['item']['agent_enabled']
    retry = client.post(uri + '/checklist-action', json=raw)
    assert retry.status_code == 200 and retry.json()['duplicate']
    assert retry.json()['item']['id'] == saved.json()['item']['id']
    assert len(ideas.followups.list()) == 2


@pytest.mark.parametrize('entry', ['card', 'editor', 'shared-editor'])
@pytest.mark.parametrize('width', [390, 1280])
def test_create_action_from_checklist(editor_page, entry, width, tmp_path):
    from playwright.sync_api import expect
    page, client = editor_page
    parent = create_action(client)
    uri = '/hfl-corpus/timeline/items/' + parent['id']
    text = 'Build a detailed checklist experience with long wrapping text and ' + 'unbroken' * 15
    parent['checklists'][0]['items'][1]['text'] = text
    parent = client.patch(uri, json={'version': parent['version'], 'checklists': parent['checklists']}).json()['item']
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto('https://editing.test/hfl-corpus/actions')
    card = page.locator('.followups-lanes [data-followup-id="' + parent['id'] + '"]')
    expect(card).to_be_visible()
    row = card.locator('.checklist-card-row').first
    expect(row.get_by_role('button', name='Create action from item')).to_be_visible()
    assert row.evaluate('(e) => e.scrollWidth <= e.clientWidth')
    page.screenshot(path=str(tmp_path / f'checklist-card-{width}.png'))

    def start():
        if entry == 'card':
            card.get_by_role('button', name='Create action from item').first.click()
        else:
            if entry == 'editor':
                card.get_by_role('button', name='Edit', exact=True).click()
                source = page.locator('#followup-form [data-item-id=a]')
            else:
                page.evaluate('(item) => window.HflIdeas.openEditor("actionable", item)', parent)
                source = page.locator('.idea-dialog [data-item-id=a]')
            expect(source.get_by_role('button', name='Add checklist item to board')).to_be_visible()
            assert source.evaluate('(e) => e.scrollWidth <= e.clientWidth')
            page.screenshot(path=str(tmp_path / f'checklist-editor-{entry}-{width}.png'))
            source.get_by_role('button', name='Create action from item', exact=True).click()

    start()
    draft = page.get_by_role('dialog', name='Create action from checklist item', exact=True)
    expect(draft.locator('[name=title]')).to_have_value(text[:200])
    draft.get_by_role('button', name='Close editor', exact=True).click()
    assert not client.get(uri).json()['item']['checklists'][0]['items'][1]['done']
    start()
    draft.get_by_role('button', name='Create', exact=True).click()
    expect(draft).not_to_be_visible()
    assert client.get(uri).json()['item']['checklists'][0]['items'][1]['done']
    expect(card.get_by_role('checkbox').first).to_be_checked()
    expect(card.locator('.checklist-card-cover > p')).to_have_text('First · 2/2')


@pytest.mark.parametrize('editor', ['timeline', 'idea'])
@pytest.mark.parametrize('existing', [False, True])
def test_action_agent_settings(editor_page, monkeypatch, tmp_path, editor, existing):
    from playwright.sync_api import expect
    from modules.hfl_corpus import action_agents as agents
    from modules.app_settings.store import DEFAULTS
    from workflows.hfl.action_agent_store import ActionAgentStore
    page, client = editor_page
    settings = dict(DEFAULTS)
    monkeypatch.setattr(agents, 'read_settings', lambda: dict(settings))
    db = ActionAgentStore(tmp_path / 'agents.sqlite3')
    monkeypatch.setattr(agents, 'store', lambda: db)
    monkeypatch.setattr(agents.bridge, 'action_call', lambda method, path: client.get('/hfl-corpus/timeline/items' + path).json())
    item = create_action(client) if existing else {}
    if existing:
        db.configure('card:' + item['id'], {'preset':'', 'overrides':{'hermes_profile':'Custom profile'}})
    page.goto('https://editing.test/hfl-corpus/actions')
    page.wait_for_function('window.hflActions && window.HflIdeas')
    if editor == 'timeline':
        page.evaluate('(item) => window.hflActions.openEditor(item)', item or None)
        form = page.locator('#followup-form')
    else:
        page.evaluate('(item) => window.HflIdeas.openEditor("actionable", item)', item)
        form = page.locator('.idea-dialog:visible form')
    section = form.locator('[data-action-agent-settings]')
    assert not section.evaluate('(e) => e.open')
    assert section.evaluate('(e) => e.previousElementSibling.querySelector("[name=prompt]") !== null')
    section.get_by_text('Agent settings', exact=True).click()
    expect(section.locator('dl')).to_contain_text('Custom profile' if existing else 'Worker profile')
    expect(section.get_by_role('link', name='Agent default settings')).to_have_attribute('href', '/settings')
    expect(section.get_by_role('link', name='Agent default settings')).to_have_attribute('target', '_blank')
    section.get_by_text('Agent settings', exact=True).click()
    settings['agent_session_expiry_minutes'] = 75
    section.get_by_text('Agent settings', exact=True).click()
    expect(section.locator('dl')).to_contain_text('75 minutes')


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
    expect(form.get_by_role('textbox', name='Checklist name')).to_have_count(2)
    assert [checklist['title'] for checklist in client.get(uri).json()['item']['checklists']] == ['First', 'Second']
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


def test_review_ready_and_available_status_labels_preserve_api_values(editor_page, ideas):
    from playwright.sync_api import expect
    page, client = editor_page
    item = create_action(client)
    uri = '/hfl-corpus/timeline/items/' + item['id']
    assert client.patch(uri, json={'version':item['version'],'status':'active'}).status_code == 200
    idea = ideas.save_idea(payload(), 'owner')
    page.goto('https://editing.test/hfl-corpus/actions')
    lanes = page.locator('.followups-lane')
    expect(lanes.nth(0)).to_have_attribute('data-status', 'open')
    expect(lanes.nth(1)).to_have_attribute('data-status', 'active')
    expect(lanes.nth(1).locator(':scope > h3')).to_contain_text('Ready')
    expect(lanes.nth(1).locator('.action-status')).to_have_text('Ready')
    page.get_by_role('button', name='In Review', exact=True).click()
    ready = page.locator('.followups-lane[data-status=open]')
    expect(ready.locator('.action-status')).to_have_text('In Review')
    expect(ready.locator(':scope > h3')).to_contain_text('In Review')
    assert client.get(uri).json()['item']['status'] == 'open'
    ready.get_by_role('button',name='Edit',exact=True).click()
    expect(page.locator('#followup-form [name=status] option:checked')).to_have_text('In Review')
    page.get_by_role('button',name='Close follow-up editor',exact=True).click()
    page.evaluate('(id)=>window.HflIdeas.editIdea(id)',idea['id'])
    editor=page.get_by_role('dialog',name='Edit idea',exact=True)
    expect(editor.locator('[name=status] option:checked')).to_have_text('Available')
    expect(editor.locator('[name=status]')).to_have_value('suggested')


@pytest.mark.parametrize('width', [1280, 390])
def test_ideas_drawer_keeps_reading_position_after_dismiss(editor_page, ideas, width):
    from playwright.sync_api import expect
    page, _ = editor_page
    for index in range(18):
        ideas.save_idea(payload(title=f'Reading idea {index}'), 'owner')
    page.set_viewport_size({'width': width, 'height': 800})
    page.goto('https://editing.test/hfl-corpus/actions')
    page.get_by_role('button', name='Show ideas', exact=True).click()
    drawer = page.locator('#board-ideas-drawer')
    expect(drawer.locator('[data-idea-id]')).to_have_count(18)
    card = drawer.locator('[data-idea-id]').nth(8)
    card.evaluate('(el) => el.parentElement.scrollTop += el.getBoundingClientRect().top - el.parentElement.getBoundingClientRect().top - 20')
    dismissed_id = card.get_attribute('data-idea-id')
    following = drawer.locator('[data-idea-id]').nth(9)
    following_id = following.get_attribute('data-idea-id')
    offset = following.bounding_box()['y']
    card.get_by_role('button', name='Dismiss', exact=True).click()
    expect(drawer.locator(f'[data-idea-id="{dismissed_id}"]')).to_have_count(0)
    expect(drawer.locator('[data-idea-id]')).to_have_count(17)
    assert drawer.evaluate('(el) => el.scrollTop') > 0
    assert abs(drawer.locator(f'[data-idea-id="{following_id}"]').bounding_box()['y'] - offset) < 3
