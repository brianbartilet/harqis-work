import json
from datetime import datetime
from pathlib import Path

import pytest
from modules.hfl_corpus.corpus import CorpusDocument, parse_entries


@pytest.fixture
def save_page(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as routes
    text = '## Entry\nMoment: Test\nTags: #notes\n'
    document = CorpusDocument('save.md', None, 'save.md', text, datetime.now(), datetime.now(), ('notes',), (), 'Test', entries=parse_entries(text), entry_count=1)
    monkeypatch.setattr(routes.corpus_index, 'get', lambda *a: document)
    monkeypatch.setattr(routes.corpus_index, 'documents', lambda *a, **k: (document,))
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        opts = {'headless':True}
        if not Path(engine.chromium.executable_path).exists(): opts['channel'] = 'msedge'
        browser = engine.chromium.launch(**opts)
        page = browser.new_page()
        def route(r):
            req = r.request
            if not req.url.startswith('http://save.test/'):
                r.abort(); return
            if req.url.endswith('/entries/preview'):
                r.fulfill(content_type='application/json', body=json.dumps({'payload':req.post_data_json, 'filename':'save.md', 'html':'<p>Review</p>', 'enrichment':{'added_tags':['notes']}})); return
            response = authenticated_client.get(req.url.replace('http://save.test',''))
            r.fulfill(status=response.status_code, body=response.content, headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*', route)
        yield page, playwright
        browser.close()


def test_document_save_reload_has_no_dirty_prompt(save_page):
    page, expect = save_page
    page.goto('http://save.test/hfl-corpus/document/save.md')
    page.locator('[data-entry-edit]').click()
    page.locator('[data-document-edit-text]').fill('## Edited\nMoment: Saved\n')
    page.evaluate("""() => {
      const originalFetch = window.fetch;
      window.fetch = (url, options) => options?.method === 'POST' ? new Promise(resolve => window.finishSave = ok => resolve(new Response(JSON.stringify(ok ? {updated:true} : {detail:'Retry this save'}), {status:ok?200:500}))) : originalFetch(url, options);
    }""")
    dialogs = []
    page.on('dialog', lambda dialog: (dialogs.append(dialog.type), dialog.accept()))
    page.locator('[data-document-edit-save]').click()
    assert page.locator('[data-document-edit-discard]').is_disabled()
    assert page.locator('[data-document-save-status]').is_visible()
    page.evaluate('finishSave(false)')
    expect.expect(page.locator('[data-document-edit-error]')).to_have_text('Retry this save')
    assert page.locator('[data-document-edit-save]').is_enabled()
    page.locator('[data-document-edit-save]').click()
    with page.expect_navigation(): page.evaluate('finishSave(true)')
    assert not dialogs


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('upload', [False, True])
def test_manual_save_locks_until_navigation_and_recovers_errors(save_page, width, upload):
    page, pw = save_page
    page.set_viewport_size({'width':width, 'height':900})
    page.goto('http://save.test/hfl-corpus?reset=1')
    page.locator('.corpus-create-menu > summary').click()
    page.locator('[data-create-entry-open]').click()
    form = page.locator('[data-create-entry-form]')
    form.locator('[name="moment"]').fill('Keep my entry')
    form.locator('[name="what_happened"]').fill('My details')
    form.locator('[name="include_location"]').evaluate('(el) => el.checked = false')
    if upload: form.locator('[name="attachments"]').set_input_files({'name':'test.txt', 'mimeType':'text/plain', 'buffer':b'test'})
    page.evaluate("""() => {
      window.saveCalls = 0;
      const originalFetch = window.fetch;
      window.fetch = (url, options) => url === '/hfl-corpus/entries' ? new Promise(resolve => {
        window.saveCalls++; window.finishSave = ok => resolve(new Response(JSON.stringify(ok ? {} : {detail:'Save failed; retry'}), {status:ok?200:500}));
      }) : originalFetch(url, options);
      window.XMLHttpRequest = class extends EventTarget {
        constructor() { super(); this.upload = new EventTarget(); }
        open() {}
        send() {
          window.saveCalls++;
          this.upload.dispatchEvent(new ProgressEvent('progress', {lengthComputable:true, loaded:100,total:100}));
          window.finishSave = ok => {this.status=ok?200:500;this.responseText=JSON.stringify(ok?{}:{detail:'Save failed; retry'});this.dispatchEvent(new Event('load'));};
        }
      };
      window.addEventListener('beforeunload', () => sessionStorage.setItem('lockedOnExit', String(document.querySelector('[data-entry-confirm]').disabled && document.querySelector('[data-entry-review-back]').disabled)));
    }""")
    for succeeds in (False, True):
        form.locator('[data-entry-review]').click()
        page.locator('[data-entry-confirm]').click()
        assert page.locator('[data-entry-confirm]').is_disabled()
        assert page.locator('[data-entry-review-back]').is_disabled()
        panel = page.locator('[data-entry-upload-progress]')
        assert panel.is_visible()
        gap = panel.bounding_box()['y'] - sum(page.locator('[data-entry-enrichment-summary]').bounding_box()[k] for k in ('y','height'))
        assert gap >= 12
        page.keyboard.press('Escape')
        assert page.locator('[data-entry-review-dialog]').is_visible()
        page.locator('[data-entry-confirm]').dispatch_event('click')
        assert page.evaluate('saveCalls') == (2 if succeeds else 1)
        if succeeds:
            with page.expect_navigation(): page.evaluate('finishSave(true)')
            assert 'created=true' in page.url
            assert page.evaluate("sessionStorage.getItem('lockedOnExit')") == 'true'
        else:
            page.evaluate('finishSave(false)')
            error = form.locator('[data-entry-error]')
            pw.expect(error).to_have_text('Save failed; retry')
            assert error.bounding_box()['y'] >= 0 and error.bounding_box()['y'] < 900
            assert form.locator('[data-entry-review]').is_enabled()
            assert form.locator('[name="moment"]').input_value() == 'Keep my entry'
