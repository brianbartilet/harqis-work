import json
from pathlib import Path

import pytest

from modules.hfl_corpus import quick_notes as qn, workspace_views
from modules.hfl_shares.security import make_csrf_token

deliver_events = qn.deliver_events


@pytest.fixture(autouse=True)
def notes_store(monkeypatch):
    monkeypatch.setattr(qn, 'deliver_events', lambda owner: None)
    monkeypatch.setattr(qn, 'space_context', lambda: {'views': [], 'active': []})
    with qn.connection() as db:
        qn.schema(db)
        db.execute('DELETE FROM quick_notes')
        db.execute('DELETE FROM quick_note_events')
    yield
    with qn.connection() as db:
        db.execute('DELETE FROM quick_notes')
        db.execute('DELETE FROM quick_note_events')


def test_lifecycle_revisions_and_owner_isolation(authenticated_client):
    client = authenticated_client
    url = '/hfl-corpus/quick-notes/note1'
    headers = {'X-CSRF-Token': make_csrf_token('frontend-test-user')}
    payload = {'title': 'Pack', 'items': [{'id': 'one', 'text': '**Passport** https://example.com'}]}
    assert client.put(url, json=payload).status_code == 403
    result = client.put(url, json=payload, headers=headers)
    assert result.status_code == 200, result.text
    assert '<strong>Passport</strong>' in result.json()['items'][0]['html']
    assert 'href="https://example.com"' in result.json()['items'][0]['html']
    assert not qn.listing('another-owner')['notes']
    assert client.put(url, json=payload, headers=headers).status_code == 409
    payload.update(revision=1, pinned=True)
    assert client.put(url, json=payload, headers=headers).status_code == 200
    payload.update(revision=2, archived=True)
    assert client.put(url, json=payload, headers=headers).status_code == 200
    payload.update(revision=3, archived=False)
    assert client.put(url, json=payload, headers=headers).status_code == 200
    payload['revision'] = 4
    assert client.delete(url, headers=headers).status_code == 422
    assert client.request('DELETE', url, json=payload, headers=headers).status_code == 200
    assert client.get('/hfl-corpus/quick-notes').json()['notes'] == []
    assert client.put(url, json=payload, headers=headers).status_code == 409
    with qn.connection() as db:
        assert [json.loads(r[0])['operation'] for r in db.execute('SELECT payload FROM quick_note_events')] == ['created', 'archived', 'deleted']


def test_space_union_and_safe_markdown(monkeypatch):
    qn.save('owner', 'global', qn.Note(items=[qn.Item(id='one', text='<script>alert(1)</script> [bad](javascript:alert)')]))
    qn.save('owner', 'work', qn.Note(workspace_ids=['work']))
    qn.save('owner', 'home', qn.Note(workspace_ids=['home']))
    monkeypatch.setattr(qn, 'space_context', lambda: {'active': ['work']})
    result = qn.listing('owner')['notes']
    assert {n['id'] for n in result} == {'global', 'work'}
    assert '<script' not in result[0]['items'][0]['html']
    assert 'href="javascript:' not in result[0]['items'][0]['html']
    monkeypatch.setattr(qn, 'space_context', lambda: {'active': ['work', 'home']})
    assert len(qn.listing('owner')['notes']) == 3


def test_tree_validation():
    with pytest.raises(ValueError):
        qn.Note(items=[qn.Item(id='child', parent='missing')])
    with pytest.raises(ValueError):
        qn.Note(items=[qn.Item(id='a'), qn.Item(id='b', parent='a'), qn.Item(id='c', parent='b')])
    with pytest.raises(ValueError):
        qn.Note(items=[qn.Item(id='a'), qn.Item(id='a')])


def test_lifecycle_delivery_retries_with_stable_identity(monkeypatch):
    from workflows.hfl import persistence
    qn.save('owner', 'delivery-test', qn.Note(title='Delivery test'))
    attempts = []
    def submit(entry, **kwargs):
        attempts.append(kwargs['dedup_key'])
        assert entry.moment == 'Quick Notes created: Delivery test'
        if len(attempts) == 1:
            raise OSError('Temporary outbox failure')
        return {'delivery': 'outbox'}
    monkeypatch.setattr(persistence, 'submit_hfl_entry', submit)
    deliver_events('owner')
    with qn.connection() as db:
        assert db.execute('SELECT delivered FROM quick_note_events').fetchone()[0] == 0
    deliver_events('owner')
    deliver_events('owner')
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    with qn.connection() as db:
        assert db.execute('SELECT delivered FROM quick_note_events').fetchone()[0] == 1


def test_notes_browser(authenticated_client, monkeypatch, tmp_path):
    pw = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    errors = []
    failures = {'save': False}
    with pw.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
            def route_request(route):
                req = route.request
                if failures['save'] and '/quick-notes/' in req.url and req.method == 'PUT':
                    route.fulfill(status=503, json={'detail': 'Test connection unavailable'})
                    return
                if req.url.endswith('/hfl-corpus/workspace-views'):
                    route.fulfill(json={'views': [{'id': 'work', 'name': 'Work', 'color': '#3b82f6'}], 'active': []})
                    return
                if '/reuse/options' in req.url:
                    route.fulfill(json={'items': [{'id': 'idea-one', 'kind': 'idea', 'title': 'Packing idea', 'updated_at': '2026-11-20T09:00:00'}], 'total': 1, 'page': 1})
                    return
                if '/timeline/ideas/objects/idea-one' in req.url:
                    route.fulfill(json={'item': {'id': 'idea-one', 'title': 'Packing idea', 'updated_at': '2026-11-20T09:00:00'}})
                    return
                response = client.request(req.method, req.url.replace('https://notes.test', ''), content=req.post_data,
                    headers={k: v for k, v in req.headers.items() if k in {'content-type', 'x-csrf-token'}}, follow_redirects=True)
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k: v for k, v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}})
            context.route('https://notes.test/**', route_request)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            # The actual base shell exercises the shared assets and Butler tabs.
            page.goto('https://notes.test/home')
            page.evaluate('window.QuickNotes.open()')
            page.locator('#qn-new').click()
            page.get_by_role('textbox', name='Checklist item', exact=True).fill('**Passport** https://example.com')
            page.get_by_role('textbox', name='Checklist title', exact=True).fill('Travel kit')
            page.get_by_role('button', name='Add list item').click()
            page.get_by_role('textbox', name='Checklist item', exact=True).fill('Tickets')
            page.get_by_role('textbox', name='Checklist title', exact=True).click()
            pw.expect(page.locator('#qn-grid')).to_be_visible()
            assert page.locator('#qn-note-dialog').bounding_box()['width'] == 480
            rows = page.locator('#qn-editor .qn-row')
            rows.last.get_by_role('button', name='Drag item').drag_to(rows.first, target_position={'x': 65, 'y': 28})
            pw.expect(page.get_by_role('button', name='Indent item', exact=True)).to_have_count(0)
            pw.expect(page.locator('#qn-editor .qn-row[data-child=true]')).to_have_count(1)
            page.locator('#qn-editor .qn-row input[type=checkbox]').first.check()
            pw.expect(page.locator('#qn-editor .qn-row input[type=checkbox]').last).to_be_checked()
            page.locator('#qn-editor').get_by_role('button', name='Pin note', exact=True).click()
            page.locator('#qn-editor .qn-linker summary').click()
            page.locator('#qn-editor .qn-linker input[value=work]').check()
            page.locator('#qn-editor .qn-linker summary').click()
            page.get_by_role('searchbox', name='Find actions or ideas').fill('Packing')
            page.get_by_role('button', name='Packing idea', exact=True).click()
            pw.expect(page.locator('#qn-editor .qn-ref')).to_contain_text('Packing idea')
            assert page.locator('#qn-editor .qn-reference-search').bounding_box()['y'] < page.locator('#qn-editor .qn-ref').bounding_box()['y']
            assert page.locator('#qn-editor .qn-reference-grid').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length') == 2
            page.screenshot(path=str(tmp_path/'quick-note-editor.png'))
            page.get_by_role('button', name='Remove item', exact=True).first.click()
            pw.expect(page.locator('#qn-editor .qn-row')).to_have_count(0)
            page.get_by_role('button', name='Undo removal').click()
            pw.expect(page.locator('#qn-editor .qn-row')).to_have_count(2)
            failures['save'] = True
            page.get_by_role('textbox', name='Checklist title', exact=True).fill('Travel kit revised')
            pw.expect(page.locator('#qn-retry')).to_be_visible()
            page.get_by_role('button', name='Close note', exact=True).click()
            pw.expect(page.locator('#qn-note-dialog')).to_be_visible()
            failures['save'] = False
            page.locator('#qn-retry').click()
            pw.expect(page.locator('#qn-status')).to_have_text('Saved')
            page.get_by_role('textbox', name='Checklist title', exact=True).fill('Travel kit')
            page.get_by_role('button', name='Close note', exact=True).click()
            pw.expect(page.locator('#qn-grid')).to_contain_text('Travel kit')
            pw.expect(page.locator('#qn-grid strong')).to_have_text('Passport')
            page.screenshot(path=str(tmp_path/'quick-notes-desktop.png'))
            stored = client.get('/hfl-corpus/quick-notes').json()['notes'][0]
            assert stored['workspace_ids'] == ['work']
            assert stored['references'] == [{'id': 'idea-one', 'kind': 'idea'}]
            # Toggle after an autosave: handlers must still edit the current model.
            page.locator('#qn-grid .qn-row input[type=checkbox]').first.uncheck()
            pw.expect(page.locator('#qn-status')).to_have_text('Saved')
            saved = client.get('/hfl-corpus/quick-notes').json()['notes'][0]
            assert not any(i['completed'] for i in saved['items'])
            page.locator('#qn-grid .qn-row input[type=checkbox]').first.check()
            page.locator('#qn-close').click()
            page.locator('#butler-launch').click()
            page.locator('#butler-tab-notes').click()
            pw.expect(page.locator('#butler-notes-list')).to_contain_text('Travel kit')
            page.locator('#butler-notes-list input[type=checkbox]').last.uncheck()
            pw.expect(page.locator('#butler-notes-playback')).to_have_attribute('aria-label', 'Resume scrolling')
            page.locator('#butler-notes-list .qn-title').click()
            pw.expect(page.locator('#quick-notes-dialog')).to_be_visible()
            page.mouse.click(180, 100)
            pw.expect(page.locator('#qn-note-dialog')).not_to_be_visible()
            page.locator('#qn-grid').get_by_role('button', name='Archive', exact=True).click()
            pw.expect(page.locator('#qn-grid')).not_to_contain_text('Travel kit')
            page.locator('#qn-archive').click()
            pw.expect(page.locator('#qn-grid')).to_contain_text('Travel kit')
            page.locator('#qn-grid').get_by_role('button', name='Restore', exact=True).click()
            page.locator('#qn-archive').click()
            pw.expect(page.locator('#qn-grid')).to_contain_text('Travel kit')
            page.set_viewport_size({'width': 390, 'height': 844})
            writes = []
            page.on('request', lambda request: writes.append(request.url) if request.method == 'PUT' and '/quick-notes/' in request.url else None)
            page.locator('#qn-grid .qn-row .qn-line').last.click()
            inline = page.get_by_role('textbox', name='Checklist item', exact=True)
            inline.fill('Tickets updated')
            inline.press('Enter')
            pw.expect(inline).to_be_focused()
            pw.expect(inline).to_have_value('')
            inline.fill('Boarding pass')
            pw.expect(page.locator('#qn-grid .qn-row')).to_have_count(3)
            # Enter keeps the editing session open past the old autosave delay.
            page.wait_for_timeout(650)
            assert not writes
            page.locator('#quick-notes-title').click()
            pw.expect(page.locator('#qn-status')).to_have_text('Saved')
            saved = client.get('/hfl-corpus/quick-notes').json()['notes'][0]
            assert [item['text'] for item in saved['items']][1:] == ['Tickets updated', 'Boarding pass']
            assert saved['items'][2]['parent'] == saved['items'][1]['parent']
            page.screenshot(path=str(tmp_path/'quick-notes-mobile.png'))
            assert page.locator('#qn-grid').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length') == 1
            assert page.locator('#quick-notes-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            qn.save('frontend-test-user', 'drag-a', qn.Note(title='Drag A', order=0))
            qn.save('frontend-test-user', 'drag-b', qn.Note(title='Drag B', order=1))
            page.evaluate('window.QuickNotes.open()')
            page.set_viewport_size({'width': 1280, 'height': 900})
            pw.expect(page.locator('#qn-grid .qn-title')).to_have_text(['Travel kit', 'Drag A', 'Drag B'])
            pw.expect(page.get_by_role('button', name='Move note up', exact=True)).to_have_count(0)
            first = page.locator('#qn-grid [data-note-id="drag-a"]')
            second = page.locator('#qn-grid [data-note-id="drag-b"]')
            second.drag_to(first, source_position={'x': 10, 'y': 10}, target_position={'x': 10, 'y': 10})
            pw.expect(page.locator('#qn-grid .qn-title')).to_have_text(['Travel kit', 'Drag B', 'Drag A'])
            # An unpinned note cannot displace a pinned note or change its pin state.
            second.drag_to(page.locator('#qn-grid .qn-card').first, source_position={'x': 10, 'y': 10}, target_position={'x': 10, 'y': 10})
            pw.expect(page.locator('#qn-grid .qn-title')).to_have_text(['Travel kit', 'Drag B', 'Drag A'])
            page.locator('#qn-close').click()
            pw.expect(page.locator('#quick-notes-dialog')).not_to_be_visible()
            page.evaluate('window.QuickNotes.open()')
            pw.expect(page.locator('#qn-grid .qn-title')).to_have_text(['Travel kit', 'Drag B', 'Drag A'])
            page.locator('#qn-grid .qn-card').first.get_by_role('button', name='Archive', exact=True).click()
            pw.expect(page.locator('#qn-grid .qn-title')).to_have_text(['Drag B', 'Drag A'])
            toggle = page.get_by_role('switch', name='Show archived')
            pw.expect(toggle).to_have_attribute('aria-checked', 'false')
            toggle.click()
            pw.expect(toggle).to_have_attribute('aria-checked', 'true')
            # Even a pinned archived note comes after every active note.
            pw.expect(page.locator('#qn-grid .qn-title')).to_have_text(['Drag B', 'Drag A', 'Travel kit'])
            last = page.locator('#qn-grid .qn-card').last
            pw.expect(last).to_have_attribute('data-archived', 'true')
            assert last.evaluate('(el)=>Number(getComputedStyle(el).opacity)<1')
            page.screenshot(path=str(tmp_path/'quick-notes-archived-desktop.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(tmp_path/'quick-notes-archived-mobile.png'))
            assert page.locator('#quick-notes-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
            toggle.click()
            pw.expect(page.locator('#qn-grid .qn-title')).to_have_text(['Drag B', 'Drag A'])
            assert not errors, errors
        finally:
            browser.close()
