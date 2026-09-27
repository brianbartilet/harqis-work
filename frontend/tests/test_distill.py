from pathlib import Path
from urllib.parse import urlsplit

import pytest

from frontend.tests.test_hfl_timeline import agenda, payload


def test_distill_requires_login(authenticated_client):
    authenticated_client.cookies.clear()
    response = authenticated_client.get('/distill', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'] == '/login'


@pytest.mark.parametrize('width', [390, 1440])
def test_distill_navigation_actions_and_retry(agenda, authenticated_client, monkeypatch, tmp_path, width):
    from modules.hfl_corpus import router
    monkeypatch.setattr(router.corpus_index, 'documents', lambda **kwargs: ())
    monkeypatch.setenv('HFL_AGENT_BRIDGE_STORE_PATH', str(tmp_path / 'bridge.sqlite3'))
    item = agenda.create(payload(title='Review the weekly capture', matrix='Q2'), actor='test')[0]
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        fail = [False]
        mutations = []
        def respond(route):
            url = urlsplit(route.request.url)
            if route.request.method not in ('GET', 'HEAD'): mutations.append(url.path)
            if url.path == '/hfl-corpus/timeline/ideas/snapshot':
                from datetime import date
                route.fulfill(status=200, json={'ideas': [{'id': 'idea-test', 'status': 'suggested', 'source_date': date.today().isoformat()}]}); return
            if fail[0] and url.path == '/hfl-corpus/timeline/items':
                route.fulfill(status=503, json={'detail': 'Unavailable'}); return
            response = authenticated_client.get(url.path + ('?' + url.query if url.query else ''))
            route.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get('content-type', 'text/html'))
        page.route('https://distill.test/**', respond)
        page.goto('https://distill.test/distill')
        playwright.expect(page.get_by_role('heading', level=1)).to_contain_text('what happens next')
        playwright.expect(page.locator('[data-distill-recent] a')).to_contain_text(item['title'])
        link = page.locator('[data-distill-recent] a')
        assert 'edit=' + item['id'] in link.get_attribute('href')
        assert page.get_by_role('link', name='Capture a moment').get_attribute('href') == '/hfl-corpus?create=entry'
        assert page.locator('main').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
        playwright.expect(page.locator('[data-activity-panel][data-readonly="true"]')).to_have_count(1)
        playwright.expect(page.locator('[data-activity-day][data-idea-count], [data-timeline-status="historical"]')).to_have_count(0)
        playwright.expect(page.locator('[data-activity-day][data-timeline-status]').first).to_be_attached()
        assert page.locator('[data-memory-category-new]').count() == 0
        scroll = page.locator('[data-activity-scroll]')
        page.wait_for_timeout(400)
        before = scroll.evaluate('(el) => el.scrollLeft')
        assert before > 0
        scroll.hover()
        page.mouse.wheel(0, -500)
        page.wait_for_timeout(250)
        assert scroll.evaluate('(el) => el.scrollLeft') < before
        from datetime import date
        previous = date.today().year - 1
        if width < 640:
            page.locator('[data-activity-year-trigger]').click()
        page.locator(f'[data-activity-year-option="{previous}"]').click()
        playwright.expect(page.locator(f'[data-activity-year-segment="{previous}"]')).to_have_attribute('data-activity-loaded', 'true')
        cell = page.locator(f'[data-activity-day="{previous}-07-01"]')
        cell.click()
        playwright.expect(page.locator('[data-activity-day-menu]')).to_be_hidden()
        assert page.locator('dialog[open]').count() == 0
        assert not mutations
        assert page.locator('.activity-indicator-legend').inner_text().startswith('Actions')
        page.locator('[data-activity-toggle]').click()
        playwright.expect(page.locator('[data-activity-body]')).to_be_hidden()
        page.locator('[data-activity-toggle]').click()
        playwright.expect(page.locator('[data-activity-body]')).to_be_visible()
        page.screenshot(path=str(tmp_path / ('distill-' + str(width) + '.png')), full_page=True)
        link.click()
        page.wait_for_load_state('networkidle')
        assert not page.locator('#agenda-error').inner_text(), page.locator('#agenda-error').inner_text()
        playwright.expect(page.locator('#followup-editor')).to_be_visible()
        page.goto('https://distill.test/distill')
        page.get_by_role('searchbox').fill('weekly capture')
        page.get_by_role('button', name='Search Corpus').click()
        page.wait_for_url('**/hfl-corpus?q=weekly+capture')
        page.locator('[data-activity-day][data-today="true"]').click()
        playwright.expect(page.locator('[data-activity-day-menu]')).to_be_visible()
        assert '>Active<' in page.locator('.activity-indicator-legend').inner_html()
        fail[0] = True
        page.goto('https://distill.test/distill')
        playwright.expect(page.locator('[data-distill-error]')).to_be_visible()
        fail[0] = False
        page.get_by_role('button', name='Try again').click()
        playwright.expect(page.locator('[data-distill-error]')).to_be_hidden()
        playwright.expect(page.locator('[data-distill-recent] a')).to_have_count(1)
        agenda.update(item['id'], {'version': item['version'], 'status': 'dismissed'}, actor='test')
        page.reload()
        playwright.expect(page.locator('[data-distill-recent]')).to_contain_text('No recent action cards yet')
        assert not errors
        browser.close()


def test_distill_signal_all_activity_and_auth(authenticated_client, monkeypatch):
    from modules.hfl_corpus import router
    monkeypatch.setattr(router.corpus_index, 'documents', lambda **kwargs: ())
    original = router.hfl_corpus_page
    seen = []
    async def corpus(request):
        seen.append(str(request.query_params))
        return await original(request)
    monkeypatch.setattr(router, 'hfl_corpus_page', corpus)
    response = authenticated_client.get('/distill?scope=filtered&q=hidden&show_secrets=true')
    assert response.status_code == 200
    assert 'data-readonly="true"' in response.text
    assert seen == ['']
    corpus_response = authenticated_client.get('/hfl-corpus')
    assert 'activity-indicator-legend' in corpus_response.text
    assert '>Active</span>' in corpus_response.text
