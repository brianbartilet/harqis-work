"""The checklist entry point and shortcut work on the three requested pages."""
from urllib.parse import urlparse

import pytest
from test_agent_fleet import fleet  # noqa: F401
from test_hfl_agent_bridge import bridge  # noqa: F401


@pytest.mark.parametrize('width', [1440, 390])
def test_quick_notes_page_entry_points(fleet, authenticated_client, width):
    pw = pytest.importorskip('playwright.sync_api')
    fleet.initialize()
    client = authenticated_client
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route(r):
                u = urlparse(r.request.url)
                if u.path == '/second-brain/hud/data':
                    r.fulfill(json={'items': {}, 'context': [], 'source_error': '',
                        'spaces': client.get('/hfl-corpus/workspace-views').json(),
                        'layout': {'widgets': [], 'revision': 0}})
                    return
                response = client.request(r.request.method, u.path + ('?' + u.query if u.query else ''),
                    content=r.request.post_data_buffer,
                    headers={k: v for k, v in r.request.headers.items() if k.lower() in {'content-type', 'x-csrf-token'}}, follow_redirects=True)
                r.fulfill(status=response.status_code, content_type=response.headers.get('content-type', 'text/html'), body=response.content)
            page.route('https://quick-notes.test/**', route)
            for path in ['/agents', '/second-brain', '/hfl-corpus/actions']:
                page.goto('https://quick-notes.test' + path)
                launch = page.locator('.qn-launch[data-quick-notes-open]')
                pw.expect(launch).to_have_count(1)
                pw.expect(launch).to_be_visible()
                styles = page.locator('.second-brain-navigation').evaluate('''nav => {
                    const properties = ['width', 'height', 'padding', 'borderRadius', 'borderColor', 'backgroundColor', 'color'];
                    return [nav.querySelector('a'), nav.querySelector('.qn-launch')].map(element => {
                        const style = getComputedStyle(element);
                        return Object.fromEntries(properties.map(key => [key, style[key]]));
                    });
                }''')
                assert styles[0] == styles[1], (path, styles)
                launch.click()
                pw.expect(page.get_by_role('dialog', name='Quick Notes', exact=True)).to_be_visible()
                page.locator('#qn-close').click()
                page.evaluate('document.activeElement?.blur()')
                page.keyboard.press('s')
                pw.expect(page.get_by_role('dialog', name='Quick Notes', exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                pw.expect(page.get_by_role('dialog', name='Quick Notes', exact=True)).not_to_be_visible()
                assert page.locator('script[src*="quick-notes.js?v="]').count() == 1
            assert not errors, errors
        finally:
            browser.close()
