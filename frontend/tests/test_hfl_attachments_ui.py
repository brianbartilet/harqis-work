from datetime import date
from urllib.parse import urlparse
from pathlib import Path

import pytest


def test_attachment_load_failure_allows_text_edits_and_retry_recovers_files():
    from web import templates
    playwright = pytest.importorskip('playwright.sync_api')
    markup = templates.env.get_template('modules/hfl_corpus/partials/input_attachments.html').render(memory_csrf='test')
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        attempts = []
        def respond(route):
            attempts.append(route.request.method)
            route.fulfill(status=404 if len(attempts) == 1 else 200, content_type='application/json',
                          body='{"detail":"Not Found"}' if len(attempts) == 1 else '{"attachments":[{"id":"saved","name":"brief.md","size":12}]}')
        page.route('https://inputs.test/**', respond)
        page.set_content('<base href="https://inputs.test/">' + markup)
        page.add_script_tag(path=str(Path(__file__).resolve().parents[1] / 'static/js/hfl-input-attachments.js'))
        page.evaluate("window.editor = new HflInputAttachments(document.querySelector('[data-input-editor]'), 'pin'); editor.reset('42')")
        playwright.expect(page.locator('[data-input-error]')).to_have_text('Couldn’t load saved files.')
        playwright.expect(page.locator('[data-input-choose]')).to_be_disabled()
        assert page.evaluate('() => { editor.validate(); return !editor.changed; }')
        assert page.locator('.agent-inputs .agent-input-heading').count() == 0
        page.locator('[data-input-retry]').click()
        playwright.expect(page.locator('[data-input-list] a')).to_have_text('brief.md · 1 KB')
        playwright.expect(page.locator('[data-input-status]')).to_be_hidden()
        playwright.expect(page.locator('[data-input-choose]')).to_be_enabled()
        assert attempts == ['GET', 'GET']
        browser.close()


@pytest.mark.parametrize('width', [390, 1100])
@pytest.mark.parametrize('kind', ['actionable', 'pin'])
@pytest.mark.parametrize('with_files', [True, False])
def test_editors_save_multiple_attachments_without_running_early(authenticated_client, monkeypatch, tmp_path, width, kind, with_files):
    from modules.hfl_corpus import timeline, router
    from modules.hfl_corpus.attachments import source_store
    from modules.hfl_corpus.memory_pins import get_memory_pin_store
    from workflows.hfl.timeline_store import FollowUpStore
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_STORE_PATH', str(tmp_path / 'bridge.sqlite3'))
    actions = FollowUpStore(tmp_path / 'actions.sqlite3')
    monkeypatch.setattr(timeline, 'store', lambda: actions)
    monkeypatch.setattr(router.corpus_index, 'documents', lambda: ())
    pins = get_memory_pin_store()
    pins.save_category(category_id=None, name='Tests', color='#3b82f6')
    calls = []
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request_route):
            request = request_route.request
            url = urlparse(request.url)
            if url.hostname != 'inputs.test':
                request_route.abort(); return
            if request.method == 'POST' and '/inputs/' in url.path:
                current = actions.list()[0] if kind == 'actionable' else pins.snapshot()['ranges'][0]
                assert current['prompt'] == ''
            response = authenticated_client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                content=request.post_data_buffer, headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            calls.append((request.method, url.path, response.status_code))
            request_route.fulfill(status=response.status_code, body=response.content,
                headers={'content-type': response.headers.get('content-type', 'text/html')})

        page.route('**/*', route)
        page.goto('https://inputs.test/hfl-corpus/actions' if kind == 'actionable' else 'https://inputs.test/hfl-corpus')
        if kind == 'actionable':
            page.locator('[data-board-create-menu] > summary').click()
            page.locator('[data-board-create-action]').click()
            dialog = page.locator('#followup-editor')
            dialog.locator('[name="title"]').fill('Read supporting files')
            dialog.get_by_text('Action plan', exact=True).click()
            dialog.locator('[name="expected_outcome"]').fill('A summary using both files')
            dialog.locator('[name="prompt"]').fill('Read the briefing and data')
        else:
            page.locator(f'[data-activity-day="{date.today().isoformat()}"]').click()
            page.get_by_text('Pin dates', exact=True).click()
            page.locator(f'[data-activity-day="{date.today().isoformat()}"]').click()
            dialog = page.locator('[data-memory-dialog]')
            dialog.locator('[data-memory-pin-title]').fill('Read supporting files')
            editor = dialog.locator('[data-prompt-editor="range"]')
            if not editor.locator('[data-prompt-input]').is_visible():
                editor.locator('[data-prompt-toggle]').click()
            editor.locator('[data-prompt-input]').fill('Read the briefing and data')
        widget = dialog.locator('[data-input-editor]')
        widget.locator('[data-input-files]').set_input_files([
            {'name':'brief.md', 'mimeType':'text/markdown', 'buffer':b'Briefing'},
            {'name':'data.csv', 'mimeType':'text/csv', 'buffer':b'a,b\n1,2'},
        ] if with_files else [])
        assert not widget.locator('[data-input-files]').evaluate('(el) => el.required')
        assert widget.locator('.agent-input-row').count() == (2 if with_files else 0)
        assert widget.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        dialog.locator('[type="submit"]').click()
        if kind == 'actionable':
            playwright.expect(page.locator('.editor-save-confirmation')).to_contain_text('Action saved.')
        playwright.expect(dialog).not_to_be_visible()
        item = actions.list()[0] if kind == 'actionable' else pins.snapshot()['ranges'][0]
        assert item['prompt'] == 'Read the briefing and data'
        store, source = source_store(kind, str(item['id']))
        assert [f['name'] for f in store.list(source)] == (['brief.md', 'data.csv'] if with_files else [])
        assert not errors
        assert not [call for call in calls if call[2] >= 400]
        browser.close()


@pytest.mark.parametrize('width', [390, 1100])
def test_attachment_groups_preserve_controls_and_pending_files(tmp_path, width):
    import json
    from web import templates
    playwright = pytest.importorskip('playwright.sync_api')
    frontend = Path(__file__).resolve().parents[1]
    markup = templates.env.get_template('modules/hfl_corpus/partials/input_attachments.html').render(memory_csrf='test')
    editor = (frontend / 'templates/modules/hfl_corpus/partials/action_editor.html').read_text(encoding='utf-8')
    styles = editor.split('<style>')[1].split('</style>')[0]
    files = [
        {'id': 'brief', 'name': 'brief.md', 'size': 123, 'group': 'uploaded'},
        {'id': 'report', 'name': 'b914f730-869a1886-report.md', 'size': 1024, 'group': 'generated'},
        {'id': 'transcript', 'name': 'b914f730-2d98f8f4-conversation.md', 'size': 2048, 'group': 'execution'},
    ]
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 850})
        page.route('https://inputs.test/**', lambda route: route.fulfill(content_type='application/json', body=json.dumps({'attachments': files})))
        page.set_content('<base href="https://inputs.test/"><style>body{background:#0b1220;color:#e2e8f0;font-family:Arial;max-width:580px;margin:24px auto;padding:12px}*{box-sizing:border-box}' + styles + '</style>' + markup)
        page.add_style_tag(path=str(frontend / 'static/css/hfl-timeline.css'))
        page.add_script_tag(path=str(frontend / 'static/js/hfl-input-attachments.js'))
        page.evaluate("window.editor=new HflInputAttachments(document.querySelector('[data-input-editor]'),'actionable');editor.reset('test')")
        playwright.expect(page.locator('[data-file-group=uploaded] summary')).to_have_text('Uploaded attachments · 1')
        playwright.expect(page.locator('[data-file-group=generated] summary')).to_have_text('Generated outputs · 1')
        execution = page.locator('[data-file-group=execution]')
        playwright.expect(execution.locator('summary')).to_have_text('Agent execution artifacts · 1')
        assert not execution.evaluate('(el)=>el.open')
        execution.locator('summary').click()
        playwright.expect(execution.get_by_role('button', name='Preview ' + files[2]['name'], exact=True)).to_be_visible()
        page.locator('[data-input-files]').set_input_files({'name': 'new.txt', 'mimeType': 'text/plain', 'buffer': b'New'})
        playwright.expect(page.locator('[data-file-group=uploaded] summary')).to_have_text('Uploaded attachments · 2')
        assert execution.evaluate('(el)=>el.open')
        page.get_by_role('button', name='Remove new.txt', exact=True).click()
        playwright.expect(page.locator('[data-file-group=uploaded] summary')).to_have_text('Uploaded attachments · 1')
        assert not page.evaluate('editor.changed')
        assert page.locator('[data-input-editor]').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
        page.screenshot(path=str(tmp_path / ('attachment-groups-' + str(width) + '.png')))
        browser.close()


def test_saved_and_pending_attachment_preview_dialog():
    playwright = pytest.importorskip('playwright.sync_api')
    from web import templates
    markup=templates.env.get_template('modules/hfl_corpus/partials/input_attachments.html').render(memory_csrf='test')
    with playwright.sync_playwright() as driver:
        browser=driver.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page()
        def route(request_route):
            if 'view=true' in request_route.request.url:
                request_route.fulfill(status=200,content_type='text/plain',body='Previewed document text')
            else:
                request_route.fulfill(status=200,content_type='application/json',body='{"attachments":[{"id":"saved","name":"brief.txt","size":23}]}')
        page.route('https://inputs.test/**',route)
        page.set_content('<base href="https://inputs.test/">'+markup)
        page.add_script_tag(path=str(Path(__file__).resolve().parents[1]/'static/js/hfl-input-attachments.js'))
        page.evaluate("window.editor=new HflInputAttachments(document.querySelector('[data-input-editor]'),'actionable');editor.reset('test')")
        page.get_by_role('button',name='Preview brief.txt').click()
        preview=page.locator('.agent-input-preview')
        playwright.expect(preview.locator('pre')).to_have_text('Previewed document text')
        preview.get_by_role('button',name='Close',exact=True).click()
        page.locator('[data-input-files]').set_input_files({'name':'pending.txt','mimeType':'text/plain','buffer':b'Pending text'})
        page.get_by_role('button',name='Preview pending.txt').click()
        playwright.expect(preview.locator('pre')).to_have_text('Pending text')
        preview.get_by_role('button',name='Close',exact=True).click()
        playwright.expect(page.locator('.agent-input-preview')).to_have_count(0)
        browser.close()
