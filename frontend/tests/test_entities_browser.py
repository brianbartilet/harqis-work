"""Directory search, pagination and profile references with isolated data."""
from pathlib import Path

import pytest


def test_complete_directory_and_references(authenticated_client, monkeypatch, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'entities.sqlite3'))
    rows = [dict(id=str(i), label=f'Entity {i:04}', kind='topics', categories=[],
                 profile=None, entries=[], resolution='model-extracted') for i in range(1203)]
    rows[-1]['profile'] = dict(name=rows[-1]['label'], categories=[], emails=[], phones=[], notes='',
                               references=['https://social.example/unique-last-entity', 'C:\\Notes\\last.pdf'])
    monkeypatch.setattr(entities, 'entity_index', lambda *args: rows.copy())
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            if Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe').exists():
                options['channel'] = 'msedge'
            else:
                pytest.skip('Install Playwright Chromium to run directory integration')
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def route_request(route):
                request = route.request
                if request.url == 'https://entities.test/api/hfl/entities':
                    requests.append(request.url)
                response = authenticated_client.request(request.method, request.url.replace('https://entities.test', ''),
                    content=request.post_data, headers={'content-type': request.headers.get('content-type', 'application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                              headers={key: value for key, value in response.headers.items()
                                       if key.lower() not in {'content-encoding', 'content-length'}})

            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            page.wait_for_selector('#entity-results:not([hidden])')
            assert page.locator('h1').inner_text() == 'Activity Corpus Entities'
            assert page.locator('#filter-kind button').first.text_content() == 'All types1203'
            assert page.locator('.entity-card').count() == 50
            assert page.locator('#page-number').inner_text() == 'Page 1 of 25'
            assert page.locator('.profile-editor').count() == 0  # Details are built only when opened.
            page.click('#next')
            assert 'Entity 0050' in page.locator('.entity-card').first.inner_text()
            page.fill('#entity-query', 'unique-last-entity')
            assert page.locator('.entity-card').count() == 1
            assert page.locator('#page-number').inner_text() == 'Page 1 of 1'
            page.locator('.entity-card > summary').click()
            page.wait_for_selector('.profile-editor')
            assert page.get_by_role('link', name='https://social.example/unique-last-entity', exact=True).get_attribute('rel') == 'noopener noreferrer'
            assert page.locator('code').filter(has_text='C:\\Notes\\last.pdf').count() == 1
            page.locator('.profile-editor > summary').click()
            page.locator('textarea[name="references"]').fill('https://example.com/new-reference')
            page.get_by_role('button', name='Save profile', exact=True).click()
            page.wait_for_function("document.querySelector('#entity-status').textContent.includes('Profile saved.')")
            page.fill('#entity-query', 'new-reference')
            assert page.locator('.entity-card').count() == 1
            assert page.locator('#filter-kind button').first.text_content() == 'All types1203'
            page.click('#clear-filters')
            assert page.locator('.entity-card').count() == 50
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert len(requests) == 1  # Searching and paging use the complete loaded directory.
            assert not errors
        finally:
            browser.close()


def test_bulk_selection_merge_and_unmerge(authenticated_client, monkeypatch, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    from workflows.hfl.entity_store import get_store
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'bulk.sqlite3'))
    monkeypatch.setattr(entities, 'current_entries', lambda: [])
    monkeypatch.setattr('workflows.hfl.persistence.submit_hfl_entry', lambda *args, **kwargs: {'delivery': 'outbox'})
    for index in range(60):
        get_store().save_profile(f'topic-{index}', 'topics', dict(name=f'Topic {index:02}',
            categories=['Testing'], emails=[], phones=[], references=[f'https://example.test/{index}'], notes=f'Note {index}'))
    get_store().save_profile('person', 'people', dict(name='Zoe', categories=[], emails=[], phones=[], references=[], notes=''))
    import json
    with get_store().connection() as db:
        db.execute("INSERT INTO entity_match_jobs(id,mode,seeds,state) VALUES ('browser-job','history','[]','complete')")
        suggestion = {'entity_ids':['topic-0','topic-1'], 'names':['Topic 00','Topic 01'],
                      'decision':{'reason':'Possible shared identity; please review.','facts':[]}}
        db.execute("INSERT INTO entity_match_pairs(id,job_id,left_id,right_id,state,data) VALUES ('browser-suggestion','browser-job','topic-0','topic-1','suggested',?)", (json.dumps(suggestion),))
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            if Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe').exists():
                options['channel'] = 'msedge'
            else:
                pytest.skip('Install Playwright Chromium to run directory integration')
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 960})
            errors, waiting_states = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def route_request(route):
                request = route.request
                if request.method == 'POST' and ('/merge-preview' in request.url or '/merges' in request.url):
                    waiting_states.append(page.locator('#merge-wait').is_visible())
                    assert page.locator('#merge-confirm').is_disabled()
                response = authenticated_client.request(request.method, request.url.replace('https://entities.test', ''),
                    content=request.post_data, headers={'content-type': request.headers.get('content-type', 'application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                              headers={key: value for key, value in response.headers.items()
                                       if key.lower() not in {'content-encoding', 'content-length'}})

            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            page.wait_for_selector('#entity-results:not([hidden])')
            page.locator('#matching-panel > summary').click()
            page.locator('#matching-suggestions details > summary').click()
            page.get_by_role('button',name='Review suggested merge',exact=True).click()
            page.wait_for_selector('#entity-merge-dialog[open]')
            assert page.locator('#merge-evidence').input_value() == 'Possible shared identity; please review.'
            page.click('#merge-close')
            page.locator('#matching-suggestions').get_by_role('button',name='Keep separate',exact=True).click()
            page.wait_for_function("document.querySelector('#matching-suggestions').textContent.includes('No uncertain matches')")
            page.click('#clear-selection')
            page.get_by_role('checkbox', name='Select Topic 00', exact=True).check()
            assert page.locator('#selection-count').inner_text() == '1 selected · Topics'
            page.click('#next')
            assert page.get_by_role('checkbox', name='Select Zoe', exact=True).is_disabled()
            page.get_by_role('checkbox', name='Select Topic 50', exact=True).check()
            page.fill('#entity-query', 'Topic 01')
            assert page.locator('#selection-count').inner_text() == '2 selected · Topics'
            page.click('#select-page')
            assert page.locator('#selection-count').inner_text() == '3 selected · Topics'
            page.click('#clear-filters')
            page.click('#select-matching')
            assert page.locator('#selection-count').inner_text() == '60 selected · Topics'
            page.click('#merge-selected')
            page.fill('#merge-name', 'Combined topics')
            page.fill('#merge-evidence', 'Same subject across aliases')
            page.click('#merge-review')
            page.wait_for_selector('#merge-preview-content:not([hidden])')
            assert '60 entities' in page.locator('#merge-preview-content').inner_text()
            page.locator('[data-merge-field="categories"]').fill('Reviewed category')
            page.locator('[data-merge-field="emails"]').fill('reviewed@example.test')
            page.locator('[data-merge-field="phones"]').fill('+65 1234 5678')
            page.locator('[data-merge-field="references"]').fill('https://example.test/reviewed')
            page.locator('[data-merge-field="notes"]').fill('Reviewed merge notes')
            page.click('#merge-review')
            page.wait_for_function("!document.querySelector('#merge-confirm').disabled")
            assert page.locator('[data-merge-field="notes"]').input_value() == 'Reviewed merge notes'
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.locator('#entity-merge-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
            page.screenshot(path=str(tmp_path / 'merge-preview-mobile.png'))
            page.click('#merge-confirm')
            page.wait_for_selector('#entity-merge-dialog', state='hidden')
            page.wait_for_function("document.querySelector('#filter-kind button').textContent === 'All types2'")
            assert page.locator('.entity-card').count() == 2
            saved = next(p for p in get_store().profiles().values() if p['name'] == 'Combined topics')
            assert saved['categories'] == ['Reviewed category']
            assert saved['emails'] == ['reviewed@example.test']
            assert saved['phones'] == ['+65 1234 5678']
            assert saved['references'] == ['https://example.test/reviewed']
            assert saved['notes'] == 'Reviewed merge notes'
            page.locator('.entity-card > summary').filter(has_text='Combined topics').click()
            page.get_by_text('Entity audit history', exact=True).click()
            page.wait_for_function("document.querySelector('.entity-audit').textContent.includes('Same subject across aliases')")
            page.get_by_role('button', name='Unmerge', exact=True).click()
            page.get_by_role('button', name='Confirm unmerge', exact=True).click()
            page.wait_for_selector('#entity-merge-dialog', state='hidden')
            page.wait_for_function("document.querySelector('#filter-kind button').textContent === 'All types61'")
            assert page.locator('.entity-card').count() == 50
            assert len(waiting_states) == 4 and all(waiting_states)
            assert not errors
        finally:
            browser.close()

