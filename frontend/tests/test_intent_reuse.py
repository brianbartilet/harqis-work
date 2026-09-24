"""Copies, live lists, recurrence, and editor interactions preserve user intent."""
from datetime import date
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas, BASE, payload


def test_copy_destinations_paginate_and_search_descriptions(ideas, authenticated_client):
    for index in range(12):
        ideas.save_idea(payload(title=f'Destination {index}', description=f'Details {index}'), 'owner')
    first = authenticated_client.get(BASE + '/reuse/options').json()
    second = authenticated_client.get(BASE + '/reuse/options?page=2').json()
    assert first['total'] == second['total'] == 12
    assert len(first['items']) == 10 and len(second['items']) == 2
    assert not {item['id'] for item in first['items']} & {item['id'] for item in second['items']}
    found = authenticated_client.get(BASE + '/reuse/options?query=Details%2011').json()
    assert found['total'] == 1 and found['items'][0]['title'] == 'Destination 11'
    assert authenticated_client.get(BASE + '/reuse/options?page=0').status_code == 422


def test_copy_list_preserves_checks_and_is_retry_safe(ideas, authenticated_client):
    target = ideas.save_idea(payload(checklists=[]), 'owner')
    raw = dict(request_id=str(uuid4()), kind='idea', identity=target['id'], version=1, checklist=payload()['checklists'][0])
    response = authenticated_client.post(BASE + '/reuse/copy-list', json=raw)
    assert response.status_code == 200, response.text
    copied = response.json()['item']['checklists'][0]
    assert copied['id'] != 'list' and copied['items'][0]['id'] != 'task'
    assert copied['items'][0]['done'] is True
    assert authenticated_client.post(BASE + '/reuse/copy-list', json=raw).json() == response.json()
    assert len(ideas.idea(target['id'])['checklists']) == 1
    assert authenticated_client.post(BASE + '/reuse/copy-list', json={**raw, 'request_id': str(uuid4())}).status_code == 409


@pytest.mark.parametrize('kind', ['idea', 'actionable'])
def test_clone_copies_files_and_rolls_back_on_missing_file(ideas, authenticated_client, kind):
    client = authenticated_client
    if kind == 'idea':
        item = ideas.save_idea(payload(workspace_ids=['work', 'home']), 'owner')
    else:
        item, _ = ideas.followups.create(payload(expected_outcome='Useful result', workspace_ids=['work', 'home'], due_date='2099-01-31',
            recurrence=dict(frequency='monthly', interval=1, start='2099-01-31', end='')), actor='owner')
    from modules.hfl_corpus.attachments import source_store
    files, source = source_store(kind, item['id'])
    import asyncio
    from starlette.datastructures import UploadFile
    from io import BytesIO
    asyncio.run(files.upload(source, [UploadFile(BytesIO(b'Notes'), filename='notes.txt')]))
    url = BASE + '/reuse/clone/' + kind + '/' + item['id']
    draft = client.get(url).json()
    raw = dict(request_id=str(uuid4()), source_version=item['version'], item=draft['item'], attachments=['missing'])
    assert client.post(url, json=raw).status_code == 409
    assert len(ideas.ideas() if kind == 'idea' else ideas.followups.list()) == 1
    raw['attachments'] = [draft['attachments'][0]['id']]
    response = client.post(url, json=raw)
    assert response.status_code == 200, response.text
    clone = response.json()['item']
    assert client.post(url, json=raw).json() == response.json()
    assert clone['workspace_ids'] == ['work', 'home']
    assert not clone['checklists'][0]['items'][0]['done']
    assert not clone.get('due_date') and not clone.get('recurrence')
    copied_files = files.list(kind + ':' + clone['id'])
    assert copied_files[0]['id'] != draft['attachments'][0]['id']
    assert files.path(copied_files[0]).read_bytes() == b'Notes'
    prefix = 'idea:' if kind == 'idea' else 'action:'
    assert any(link['source'] == prefix + clone['id'] and link['target'] == prefix + item['id'] for link in ideas.links())


def test_lists_stay_live_across_boards_and_support_layout(ideas, authenticated_client):
    client = authenticated_client
    owner = ideas.save_idea(payload(), 'owner')
    identity = 'list:idea:' + owner['id'] + ':list'
    boards = [ideas.save_map(dict(request_id=str(uuid4()), name=name, members=[identity], positions={})) for name in ('One', 'Two')]
    first = client.get(BASE + '/maps/' + boards[0]['id'] + '/graph').json()
    thought = next(n for n in first['nodes'] if n['kind'] == 'thoughts')
    assert thought['done']
    response = client.patch(BASE + '/maps/' + boards[0]['id'], json=dict(version=1, positions={thought['id']: {'x': 20, 'y': 40}}))
    assert response.status_code == 200, response.text
    checklist = owner['checklists'][0]
    checklist['items'][0].update(text='**Updated** thought', done=False)
    response = client.patch(BASE + '/lists/' + identity, json=dict(version=owner['version'], checklist=checklist))
    assert response.status_code == 200, response.text
    for board in boards:
        graph = client.get(BASE + '/maps/' + board['id'] + '/graph').json()
        live = next(n for n in graph['nodes'] if n['id'] == thought['id'])
        assert live['label'] == '**Updated** thought' and not live['done']
    assert ideas.idea(owner['id'])['checklists'][0]['items'][0]['text'] == '**Updated** thought'
    response = client.post(BASE + '/lists', json=dict(request_id=str(uuid4()), checklist=payload()['checklists'][0]))
    assert response.status_code == 200, response.text


def test_board_paste_is_atomic_and_copies_selected_edges(ideas, authenticated_client):
    idea = ideas.save_idea(payload(), 'owner')
    source_id = 'idea:' + idea['id']
    board = ideas.save_map(dict(request_id=str(uuid4()), name='Copies', members=[source_id], drafts=[dict(id='draft:a', title='Thought', body='Notes')],
                               edges=[dict(source='draft:a', target=source_id, relation='supports')], positions={}))
    raw = dict(request_id=str(uuid4()), source_board=board['id'], source_version=1, version=1, selected=['draft:a', source_id])
    response = authenticated_client.post(BASE + '/maps/' + board['id'] + '/paste', json=raw)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result['item']['drafts']) == 2 and len(result['item']['members']) == 2
    assert result['item']['drafts'][-1]['title'] == 'Thought (1)'
    assert result['item']['edges'][-1]['target'] == result['mapping'][source_id]
    assert authenticated_client.post(BASE + '/maps/' + board['id'] + '/paste', json=raw).json() == result
    assert len(ideas.ideas()) == 2
    bad = {**raw, 'request_id': str(uuid4()), 'source_version': 2, 'version': 2, 'selected': ['entry:forbidden']}
    assert authenticated_client.post(BASE + '/maps/' + board['id'] + '/paste', json=bad).status_code == 422


def test_recurrence_is_anchored_and_completion_is_idempotent(ideas):
    from workflows.hfl.intent_reuse import next_occurrence
    rule = dict(frequency='monthly', interval=1, start='2099-01-31', end='')
    assert next_occurrence(rule, date(2099, 1, 31)) == '2099-02-28'
    assert next_occurrence(rule, date(2099, 2, 28)) == '2099-03-31'
    assert next_occurrence({**rule, 'end': '2099-02-28'}, date(2099, 2, 28)) is None
    store = ideas.followups
    item, _ = store.create(payload(expected_outcome='Repeat me', due_date='2099-01-31', recurrence=rule), actor='owner')
    done = store.update(item['id'], dict(version=1, status='done'), actor='owner')
    successor = store.list()[0]
    assert successor['due_date'] == '2099-02-28'
    assert not successor['checklists'][0]['items'][0]['done']
    reopened = store.update(item['id'], dict(version=done['version'], status='open'), actor='owner')
    store.update(item['id'], dict(version=reopened['version'], status='done'), actor='owner')
    assert len(store.list()) == 1


def test_workspace_assignment_filters_actions_and_ideas(ideas, authenticated_client):
    ideas.save_idea(payload(title='Work idea', workspace_ids=['work']), 'owner')
    ideas.save_idea(payload(title='Home idea', workspace_ids=['home']), 'owner')
    rows = authenticated_client.get(BASE + '/reuse/board-ideas?workspace_ids=work').json()['items']
    assert [i['title'] for i in rows] == ['Work idea']
    for workspace in ('work', 'home'):
        ideas.followups.create(payload(title=workspace, expected_outcome='Done', workspace_ids=[workspace]), actor='owner')
    rows = authenticated_client.get('/hfl-corpus/timeline/items?workspace_ids=home').json()['items']
    assert [i['title'] for i in rows] == ['home']


@pytest.mark.parametrize('width', [1280, 390])
def test_reuse_editors_browser(ideas, authenticated_client, tmp_path, width):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    idea = ideas.save_idea(payload(title='Source idea'), 'owner')
    action, _ = ideas.followups.create(payload(title='Destination action', expected_outcome='Done', checklists=[]), actor='owner')
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def respond(route):
            r = route.request
            url = urlparse(r.url)
            response = authenticated_client.request(r.method, url.path + ('?' + url.query if url.query else ''),
                content=r.post_data_buffer, headers={'content-type': r.headers.get('content-type', 'application/json')})
            route.fulfill(status=response.status_code, body=response.content, headers={'content-type':response.headers.get('content-type', 'text/html')})
        page.route('https://reuse.test/**', respond)
        page.route('https://reuse.test/hfl-corpus/workspace-views', lambda route: route.fulfill(json={'views': [
            {'id':'work','name':'Work','color':'#f59e0b','state':{}},
            {'id':'home','name':'Home','color':'#3b82f6','state':{}},
        ]}))
        page.goto('https://reuse.test/hfl-corpus/actions')
        expect(page.locator('[data-board-all]')).to_have_count(0)
        page.locator('.board-workspace-filter > summary').click()
        page.locator('.board-workspace-filter .workspace-view-picker > summary').click()
        page.locator('.board-workspace-filter').get_by_label('Work', exact=True).check()
        page.locator('.board-workspace-filter').get_by_label('Home', exact=True).check()
        assert 'views=' not in page.url
        page.locator('.board-workspace-filter .workspace-view-picker > summary').click()
        expect(page.locator('[data-board-context]')).to_have_text('Work + Home')
        page.locator('.board-workspace-filter .workspace-view-picker > summary').click()
        page.locator('.board-workspace-filter').get_by_role('button', name='All activity', exact=True).click()
        expect(page.locator('[data-board-context]')).to_have_text('All activity')
        page.locator('.board-workspace-filter > summary').click()
        page.locator('[data-board-create-menu] > summary').click()
        expect(page.locator('[data-board-create-menu]').get_by_role('link', name='Entry')).to_be_visible()
        expect(page.locator('[data-board-create-menu]').get_by_role('button', name='Idea', exact=True)).to_be_visible()
        page.locator('[data-board-create-menu] > summary').click()

        lanes_before = page.locator('[data-board-lanes]').bounding_box()
        page.locator('.ideas-drawer-toggle').click()
        expect(page.locator('.ideas-drawer')).to_contain_text('Source idea')
        assert page.locator('[data-board-lanes]').bounding_box() == lanes_before
        assert page.locator('[data-board-lanes] > .ideas-drawer').count() == 0
        page.locator('.ideas-drawer-backdrop').click(position={'x': width - 5, 'y': 300})
        expect(page.locator('.ideas-drawer')).to_have_count(0)
        page.locator('.ideas-drawer-toggle').click()
        expect(page.locator('.ideas-drawer')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('.ideas-drawer')).to_have_count(0)
        page.locator('.ideas-drawer-toggle').click()
        expect(page.locator('.ideas-drawer')).to_contain_text('Source idea')
        page.locator('.ideas-drawer').get_by_role('button', name='Clone Source idea').click()
        modal = page.locator('dialog[open]').last
        expect(modal.get_by_label('Idea', exact=True)).to_have_value('Source idea (1)')
        assert modal.locator('[data-object-attachments] + [data-intent-fields]').count() == 1
        modal.locator('[data-intent-fields] summary').click()
        modal.locator('[data-intent-fields]').get_by_label('Work', exact=True).check()
        modal.locator('[data-intent-fields]').get_by_label('Home', exact=True).check()
        modal.locator('[data-intent-fields] summary').click()
        expect(modal.locator('[data-intent-fields] summary')).to_have_text('Work + Home')

        expect(modal.locator('.checklist-markdown')).to_contain_text('Choose a shelf')
        for revised in ('**Updated shelf**', '*Updated again*'):
            modal.locator('.checklist-markdown').click()
            checklist_input = modal.get_by_role('textbox', name='Checklist item', exact=True)
            expect(checklist_input).to_be_focused()
            checklist_input.fill(revised)
            modal.get_by_role('heading').first.click()
            expect(modal.locator('.checklist-markdown')).to_be_visible()
            expect(checklist_input).to_be_hidden()

        page.screenshot(path=str(tmp_path / ('clone-' + str(width) + '.png')), full_page=True)
        modal.get_by_role('button', name='Create', exact=True).click()
        expect(modal.locator('.editor-save-status')).to_have_text('Saved')
        expect(modal.get_by_role('button', name='Save now', exact=True)).to_have_count(0)
        assert len(ideas.ideas()) == 2
        assert next(i for i in ideas.ideas() if i['title']=='Source idea (1)')['workspace_ids'] == ['home','work']
        modal.get_by_role('button', name='Copy list', exact=True).click()
        picker = page.get_by_role('dialog', name='Copy list to action or idea')
        picker.get_by_role('searchbox').fill('Destination action')
        picker.get_by_role('button', name='Destination action · Action', exact=True).click()
        expect(picker).to_have_count(0)
        assert len(ideas.followups.get(action['id'])['checklists']) == 1
        modal.get_by_role('button', name='Close editor', exact=True).click()
        idea_card = page.locator('[data-idea-id="'+idea['id']+'"]')
        expect(idea_card.locator('.agenda-card-meta')).to_contain_text('Manual')
        expect(idea_card.get_by_role('button', name='Edit', exact=True)).to_be_visible()
        expect(idea_card.get_by_role('button', name='Promote', exact=True)).to_be_visible()
        idea_card.get_by_role('button', name='Add to board', exact=True).click()
        board_picker = page.get_by_role('dialog', name='Add to board', exact=True)
        expect(board_picker.get_by_text('Create a new board and add idea', exact=True)).to_be_visible()
        board_picker.get_by_role('button', name='Close editor', exact=True).click()
        expect(page.locator('.ideas-drawer').get_by_role('button', name='New idea')).to_have_count(0)
        page.screenshot(path=str(tmp_path / ('ideas-drawer-' + str(width) + '.png')), full_page=True)
        idea_card.get_by_role('button', name='Dismiss', exact=True).click()
        expect(idea_card).to_have_count(0)
        assert ideas.idea(idea['id'])['status'] == 'dismissed'
        page.get_by_role('button', name='Close ideas drawer', exact=True).click()
        page.locator('[data-followup-id="'+action['id']+'"]').get_by_role('button', name='Edit', exact=True).click()
        action_form = page.locator('#followup-form')
        assert action_form.locator('[data-object-attachments] + [data-intent-fields]').count() == 1
        action_form.locator('[data-intent-fields] summary').click()
        action_form.locator('[data-intent-fields]').get_by_label('Home', exact=True).check()
        action_form.locator('[data-intent-fields] summary').click()
        action_form.get_by_text('Action plan', exact=True).click()
        action_form.get_by_label('Repeat', exact=True).select_option('monthly')
        action_form.get_by_label('First planned date').fill('2099-01-31')
        expect(action_form.locator('.editor-save-status')).to_have_text('Saved')
        expect(action_form.locator('button[type=submit]')).to_be_hidden()
        expect(action_form.get_by_label('Repeat', exact=True)).to_have_value('monthly')
        assert ideas.followups.get(action['id'])['workspace_ids'] == ['home']
        action_form.evaluate("""form => {const transfer=new DataTransfer();transfer.items.add(new File(['image'], 'screenshot.png', {type:'image/png'}));form.dispatchEvent(new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true}));}""")
        expect(action_form.locator('[data-input-list]')).to_contain_text('screenshot.png')
        page.screenshot(path=str(tmp_path / ('reuse-' + str(width) + '.png')), full_page=True)
        assert not errors, errors
        browser.close()


def test_live_list_and_board_clipboard_browser(ideas, authenticated_client, tmp_path):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    idea = ideas.save_idea(payload(), 'owner')
    list_id = 'list:idea:' + idea['id'] + ':list'
    board = ideas.save_map(dict(request_id=str(uuid4()), name='Live lists', members=[list_id],
                               drafts=[dict(id='draft:one', title='Independent thought', body='Notes')]))
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def respond(route):
            r, url = route.request, urlparse(route.request.url)
            response = authenticated_client.request(r.method, url.path + ('?' + url.query if url.query else ''), content=r.post_data_buffer,
                headers={'content-type':r.headers.get('content-type', 'application/json')})
            route.fulfill(status=response.status_code, body=response.content, headers={'content-type':response.headers.get('content-type', 'text/html')})
        page.route('https://lists.test/**', respond)
        page.goto('https://lists.test/hfl-corpus/graph?board=' + board['id'])
        expect(page.locator('#kg-map-count')).to_contain_text('3 nodes')
        node_list = page.locator('#kg-list')
        node_list.get_by_role('button').filter(has_text='Independent thought').click()
        page.keyboard.press('Control+c')
        page.keyboard.press('Control+v')
        expect(page.locator('#kg-map-count')).to_contain_text('4 nodes')
        assert any(d['title'] == 'Independent thought (1)' for d in ideas.map(board['id'])['drafts'])
        page.keyboard.press('Delete')
        expect(page.locator('#kg-map-count')).to_contain_text('3 nodes')
        page.get_by_role('menuitem', name='Clear selection', exact=True).click()
        node_list.get_by_role('button').filter(has_text='Prepare').click()
        page.get_by_role('menuitem', name='Edit live list', exact=True).click()
        modal = page.locator('dialog[open]').last
        modal.get_by_label('Checklist name').fill('Synced list')
        modal.get_by_role('button', name='Save list', exact=True).click()
        expect(page.locator('#kg-detail').get_by_role('heading', name='Synced list', exact=True)).to_be_visible()
        assert ideas.idea(idea['id'])['checklists'][0]['title'] == 'Synced list'
        page.locator('.board-controls').get_by_role('button', name='New list', exact=True).click()
        modal = page.locator('dialog[open]').last
        modal.get_by_label('Checklist name').fill('Standalone')
        modal.get_by_role('button', name='Add item', exact=True).click()
        modal.get_by_label('Checklist item', exact=True).fill('**Fresh thought**')
        modal.get_by_role('button', name='Save list', exact=True).click()
        expect(page.locator('#kg-map-count')).to_contain_text('5 nodes')
        page.screenshot(path=str(tmp_path / 'live-list-board.png'), full_page=True)
        assert not errors, errors
        browser.close()
