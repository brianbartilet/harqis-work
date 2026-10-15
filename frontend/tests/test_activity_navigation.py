from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.mark.parametrize('width', [1440, 390])
def test_activity_navigation_keyboard_and_destinations(authenticated_client, monkeypatch, tmp_path, width):
    from modules.hfl_corpus import router
    monkeypatch.setattr(router.corpus_index, 'documents', lambda **kwargs: ())
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
            build = nav.get_by_role('button', name='Build', exact=True)
            tools = nav.get_by_role('navigation', name='Build tools', include_hidden=True)
            build.hover()
            playwright.expect(tools).to_be_visible()
            build.click()
            assert page.url == 'http://navigation.test/home'
            playwright.expect(tools).to_be_visible()
            assert tools.locator('a').all_text_contents() == ['Integrations', 'Workflows', 'Git Forks']
            assert tools.locator('a').evaluate_all('(links) => links.map(a => a.getAttribute("href"))') == ['/applications', '/workflows', '/git-forks']
            build.press('Escape')
            playwright.expect(tools).to_be_hidden()
            build.press('Enter')
            playwright.expect(tools).to_be_visible()
            build.press('Escape')
            build.press('ArrowDown')
            playwright.expect(tools.get_by_role('link', name='Integrations', exact=True)).to_be_focused()
            tools.get_by_role('link', name='Integrations', exact=True).press('Escape')
            assert nav.get_by_role('link', name='Distill', exact=True).get_attribute('href') == '/distill'
            toggle = nav.get_by_role('link', name='Distill', exact=True)
            menu = nav.get_by_role('navigation', name='Distill views', include_hidden=True)
            nav.get_by_role('link', name='Distill', exact=True).hover()
            playwright.expect(menu).to_be_visible()
            menu.get_by_role('link', name='Actions Kanban').hover()
            page.wait_for_timeout(350)
            playwright.expect(menu).to_be_visible()
            page.get_by_role('link', name='HARQIS home').hover()
            playwright.expect(menu).not_to_be_visible()
            toggle.focus()
            toggle.press('ArrowDown')
            playwright.expect(menu).to_be_visible()
            playwright.expect(menu.get_by_role('link', name='Activity Corpus')).to_be_focused()
            assert menu.get_by_role('link', name='Activity Corpus').get_attribute('href') == '/hfl-corpus'
            assert menu.get_by_role('link', name='Actions Kanban').get_attribute('href') == '/hfl-corpus/actions'
            bounds = menu.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            # Detect clipping by the horizontally scrolling mobile navigation.
            assert menu.get_by_role('link', name='Actions Kanban').evaluate(
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
            for destination, workspace in [('/hfl-corpus/graph', '.kg-shell'), ('/hfl-corpus/actions', '.actions-page')]:
                page.goto('http://navigation.test' + destination)
                header = page.locator('body > header')
                playwright.expect(header.get_by_role('link', name='HARQIS home')).to_be_visible()
                bounds = header.bounding_box()
                logo = header.get_by_role('link', name='HARQIS home').bounding_box()
                signout = header.get_by_role('link', name='Sign out').bounding_box()
                assert logo['x'] == (24 if width >= 1280 else 16)
                assert width - signout['x'] - signout['width'] == pytest.approx(24 if width >= 1280 else 16, abs=1)
                if width >= 1280:
                    navigation = header.locator('nav[aria-label="Primary navigation"]:visible').bounding_box()
                    assert navigation['x'] + navigation['width'] / 2 == pytest.approx(width / 2, abs=1)
                content = page.locator(workspace).bounding_box()
                assert bounds['y'] == 0
                assert content['y'] >= bounds['height']
                assert content['y'] + content['height'] <= 901
                page.evaluate('window.scrollTo(0, 1000)')
                assert header.bounding_box()['y'] == 0
                assert page.locator('[data-board-close], .kg-shell > .activity-modal-heading').count() == 0
                page.screenshot(path=str(tmp_path / f'{destination.rsplit("/", 1)[-1]}-header-{width}.png'))
            for label, destination in [('Activity Graph', '/hfl-corpus/graph'), ('Actions Kanban', '/hfl-corpus/actions')]:
                page.route('http://navigation.test' + destination + '**',
                           lambda route: route.fulfill(content_type='text/html', body='<h1>Destination</h1>'))
                page.goto('http://navigation.test/hfl-corpus?source=notes&q=launch')
                assert page.locator('.corpus-tools').count() == 0
                toggle.press('ArrowDown')
                menu.get_by_role('link', name=label).click()
                page.wait_for_url('**' + destination + '**')
                query = parse_qs(urlsplit(page.url).query)
                # Page-local Corpus filters must not follow navigation to another surface.
                assert query == {}
        finally:
            browser.close()


def test_activity_navigation_feature_disabled(authenticated_client, monkeypatch):
    monkeypatch.delenv('HARQIS_ENTITIES_DB', raising=False)
    response = authenticated_client.get('/home')
    assert response.status_code == 200
    assert 'aria-label="Distill views"' not in response.text
    assert '>Distill</a>' in response.text
