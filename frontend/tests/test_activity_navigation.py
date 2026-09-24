from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.mark.parametrize('width', [1440, 390])
def test_activity_navigation_keyboard_and_destinations(authenticated_client, monkeypatch, tmp_path, width):
    from modules.hfl_corpus import router
    monkeypatch.setattr(router.corpus_index, 'documents', lambda: ())
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def respond(route):
                url = urlsplit(route.request.url)
                response = authenticated_client.get(url.path + ('?' + url.query if url.query else ''))
                route.fulfill(status=response.status_code, body=response.content,
                              headers={k: v for k, v in response.headers.items()
                                       if k.lower() not in {'content-encoding', 'content-length'}})

            page.route('http://navigation.test/**', respond)
            page.goto('http://navigation.test/home')
            nav = page.locator('nav[aria-label="Primary navigation"]:visible')
            assert nav.get_by_role('link', name='Activity', exact=True).get_attribute('href') == '/hfl-corpus'
            toggle = nav.get_by_role('link', name='Activity', exact=True)
            menu = nav.locator('.activity-navigation-options')
            nav.get_by_role('link', name='Activity', exact=True).hover()
            playwright.expect(menu).to_be_visible()
            menu.get_by_role('link', name='Actions Board').hover()
            page.wait_for_timeout(350)
            playwright.expect(menu).to_be_visible()
            page.get_by_role('link', name='HARQIS home').hover()
            playwright.expect(menu).not_to_be_visible()
            toggle.focus()
            toggle.press('ArrowDown')
            playwright.expect(menu).to_be_visible()
            playwright.expect(menu.get_by_role('link', name='Activity Graph')).to_be_focused()
            assert menu.get_by_role('link', name='Actions Board').get_attribute('href') == '/hfl-corpus/actions'
            bounds = menu.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            # Detect clipping by the horizontally scrolling mobile navigation.
            assert menu.get_by_role('link', name='Actions Board').evaluate(
                '(el) => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }')
            page.screenshot(path=str(tmp_path / f'activity-navigation-{width}.png'))
            menu.get_by_role('link', name='Activity Graph').press('Escape')
            playwright.expect(menu).not_to_be_visible()
            playwright.expect(toggle).to_be_focused()
            toggle.press('ArrowDown')
            playwright.expect(menu).to_be_visible()
            page.get_by_role('link', name='HARQIS home').click()
            playwright.expect(menu).not_to_be_visible()
            assert not errors
            for label, destination in [('Activity Graph', '/hfl-corpus/graph'), ('Actions Board', '/hfl-corpus/actions')]:
                page.route('http://navigation.test' + destination + '**',
                           lambda route: route.fulfill(content_type='text/html', body='<h1>Destination</h1>'))
                page.goto('http://navigation.test/hfl-corpus?source=notes&q=launch')
                assert page.locator('.corpus-tools').count() == 0
                toggle.press('ArrowDown')
                menu.get_by_role('link', name=label).click()
                page.wait_for_url('**' + destination + '**')
                query = parse_qs(urlsplit(page.url).query)
                if label == 'Activity Graph':
                    query = parse_qs(query['context'][0])
                assert query['source'] == ['notes']
                assert query['q'] == ['launch']
        finally:
            browser.close()


def test_activity_navigation_feature_disabled(authenticated_client, monkeypatch):
    monkeypatch.delenv('HARQIS_ENTITIES_DB', raising=False)
    response = authenticated_client.get('/home')
    assert response.status_code == 200
    assert 'class="activity-navigation-menu"' not in response.text
    assert '>Activity</a>' in response.text
