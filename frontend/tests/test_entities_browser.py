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
                if request.url == 'http://entities.test/api/hfl/entities':
                    requests.append(request.url)
                response = authenticated_client.request(request.method, request.url.replace('http://entities.test', ''),
                    content=request.post_data, headers={'content-type': request.headers.get('content-type', 'application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                              headers={key: value for key, value in response.headers.items()
                                       if key.lower() not in {'content-encoding', 'content-length'}})

            page.route('http://entities.test/**', route_request)
            page.goto('http://entities.test/hfl-corpus/entities')
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

