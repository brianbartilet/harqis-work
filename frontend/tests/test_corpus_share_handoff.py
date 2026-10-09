import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from modules.hfl_corpus.corpus import CorpusDocument, parse_entries
from modules.hfl_shares.models import ShareConfiguration
from modules.hfl_shares.scope import build_snapshot
from modules.hfl_shares.security import make_csrf_token
from modules.hfl_shares.store import get_share_store


@pytest.fixture
def handoff_corpus(monkeypatch, tmp_path):
    import modules.hfl_corpus.router as corpus_routes
    import modules.hfl_shares.router as shares
    text = "## 2020-01-01 10:00\nEntry ID: handoff-first\nSource: notes\nMoment: Planning\nWhat happened: Plan next week\nTags: #work\nReferences:\n - https://example.com/guide\n"
    entries = parse_entries(text)
    document = CorpusDocument('handoff.md', tmp_path/'handoff.md', 'handoff.md', text,
        datetime(2026, 9, 19), datetime(2026, 9, 20), ('work',), (), 'Plan', entries=entries, entry_count=1)
    monkeypatch.setattr(corpus_routes.corpus_index, 'documents', lambda *a, **k: (document,))
    monkeypatch.setattr(shares, '_sharing_documents', lambda *a, **k: (document,))
    monkeypatch.setattr(shares, '_sharing_catalog', lambda: ((document,), ('notes',), (('work', 1),)))
    async def answer(snapshot, question):
        assert question == 'What next?'
        return 'Plan next week.'
    monkeypatch.setattr(shares, 'answer_question', answer)
    return document


def test_date_type_defaults_and_filters(handoff_corpus):
    cfg = ShareConfiguration(id='', name='Draft', recipient='Owner', sources=('notes',), date_from='2026-09-19', date_to='2026-09-19')
    assert not build_snapshot(cfg, (handoff_corpus,)).entries
    assert len(build_snapshot(replace(cfg, date_field='created'), (handoff_corpus,)).entries) == 1
    assert not build_snapshot(replace(cfg, date_field='updated'), (handoff_corpus,)).entries
    assert ShareConfiguration(**cfg.to_record()).date_field == 'entry'
    with pytest.raises(ValueError, match='date type'):
        replace(cfg, date_field='invalid')


def test_recipe_handoff_is_unsaved_and_preview_matches(authenticated_client, handoff_corpus):
    client = authenticated_client
    store = get_share_store()
    before = len(store.list_configurations()), store.count_shares()
    data = {'csrf': make_csrf_token('frontend-test-user'), 'state': json.dumps({
        'source':'notes', 'q':'#work ignored words', 'date_field':'created', 'date_from':'2026-09-19', 'date_to':'2026-09-19'})}
    assert client.post('/sharing/from-corpus', data={**data, 'csrf':'bad'}).status_code == 403
    preview = client.post('/sharing/from-corpus?mode=preview', data=data)
    assert preview.status_code == 200
    assert 'Plan next week' in preview.text and 'enabled_reference_ids' in preview.text
    import re
    reference = re.search(r'name="enabled_reference_ids" value="([^"]+)"', preview.text)[1]
    draft = client.post('/sharing/from-corpus', data={**data, 'disabled_reference_ids':reference})
    assert draft.status_code == 200
    assert 'This was generated from Activity Corpus on' in draft.text
    assert 'name="recipient" required maxlength="500" value=""' in draft.text
    assert 'value="created" selected' in draft.text
    assert 'name="disabled_reference_ids" value="'+reference+'"' in draft.text
    assert 'ignored words' not in draft.text
    chat = client.post('/sharing/from-corpus?mode=chat', data={**data, 'question':'What next?'})
    assert chat.status_code == 400
    assert 'data-test-question' not in preview.text
    assert 'data-test-question' in client.get('/sharing').text or 'data-test-agent' in client.get('/sharing').text
    assert before == (len(store.list_configurations()), store.count_shares())


@pytest.mark.parametrize('width', [390, 1440])
def test_handoff_browser(authenticated_client, handoff_corpus, width, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options = {'headless':True}
        if not Path(engine.chromium.executable_path).exists(): options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width':width,'height':900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route(r):
                req = r.request
                if not req.url.startswith('http://handoff.test/'):
                    r.abort(); return
                response = authenticated_client.request(req.method, req.url.replace('http://handoff.test',''),
                    content=req.post_data, headers={k:v for k,v in req.headers.items() if k in {'content-type','x-csrf-token'}}, follow_redirects=True)
                r.fulfill(status=response.status_code, body=response.content,
                    headers={'content-type':response.headers.get('content-type','text/html')})
            page.route('**/*', route)
            page.goto('http://handoff.test/hfl-corpus?reset=1')
            page.locator('#q').fill('#work ignored words')
            page.locator('[data-workspace-menu] > summary').click()
            page.locator('[data-corpus-share-preview]').click()
            dialog = page.locator('[data-corpus-share-dialog]')
            playwright.expect(dialog.locator('[data-preview-ready]')).to_be_visible()
            box = dialog.bounding_box()
            assert box['x'] >= 0 and box['x']+box['width'] <= width
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert dialog.locator('[data-test-question]').count() == 0
            assert dialog.locator('[data-corpus-share-chat]').count() == 0
            reference = dialog.locator('[name="enabled_reference_ids"]').first
            reference.uncheck()
            ref_id = reference.get_attribute('value')
            assert reference.bounding_box()['width'] <= 20
            dialog.evaluate('(el) => el.scrollTop = 0')
            page.screenshot(path=str(tmp_path/f'share-preview-{width}.png'), full_page=True)
            with page.expect_navigation():
                dialog.locator('[data-corpus-share-generate]').click()
            assert page.locator('#recipient').input_value() == ''
            assert page.locator('#topic').input_value() == ''
            assert 'This was generated from Activity Corpus on' in page.locator('#context-prompt').input_value()
            assert page.locator(f'[name="disabled_reference_ids"][value="{ref_id}"]').count() >= 1
            assert not errors, errors
            print('Preview screenshots:', tmp_path)
        finally:
            browser.close()
