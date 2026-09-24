"""Copies, live lists, recurrence, and editor interactions preserve user intent."""
from datetime import date
from uuid import uuid4

import pytest
from test_hfl_ideas import ideas, BASE, payload


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
        page.goto('https://reuse.test/hfl-corpus/actions')
        page.locator('.ideas-drawer-toggle').click()
        expect(page.locator('.ideas-drawer')).to_contain_text('Source idea')
        page.locator('.ideas-drawer').get_by_role('button', name='Clone Source idea').click()
        modal = page.locator('dialog[open]').last
        expect(modal.get_by_label('Idea', exact=True)).to_have_value('Source idea (1)')
        expect(modal.locator('.checklist-markdown')).to_contain_text('Choose a shelf')
        modal.get_by_role('button', name='Create', exact=True).click()
        expect(modal.get_by_role('button', name='Save now', exact=True)).to_be_visible()
        assert len(ideas.ideas()) == 2
        modal.get_by_role('button', name='Copy list', exact=True).click()
        picker = page.get_by_role('dialog', name='Copy list to action or idea')
        picker.get_by_role('searchbox').fill('Destination action')
        picker.get_by_role('button', name='Destination action · Action', exact=True).click()
        expect(picker).to_have_count(0)
        assert len(ideas.followups.get(action['id'])['checklists']) == 1
        modal.get_by_role('button', name='Close', exact=True).click()
        page.locator('[data-followup-id="'+action['id']+'"]').get_by_role('button', name='Edit', exact=True).click()
        action_form = page.locator('#followup-form')
        action_form.get_by_text('Action plan', exact=True).click()
        action_form.get_by_label('Repeat', exact=True).select_option('monthly')
        action_form.get_by_label('First planned date').fill('2099-01-31')
        action_form.get_by_role('button', name='Save now', exact=True).click()
        page.wait_for_function("() => !document.querySelector('#followup-form button[type=submit]').disabled")
        expect(action_form.get_by_label('Repeat', exact=True)).to_have_value('monthly')
        action_form.evaluate("""form => {const transfer=new DataTransfer();transfer.items.add(new File(['image'], 'screenshot.png', {type:'image/png'}));form.dispatchEvent(new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true}));}""")
        expect(action_form.locator('[data-input-list]')).to_contain_text('screenshot.png')
        page.screenshot(path=str(tmp_path / ('reuse-' + str(width) + '.png')), full_page=True)
        assert not errors, errors
        browser.close()
