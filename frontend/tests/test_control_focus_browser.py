"""Cross-module focus cascade and standalone asset coverage."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def browser():
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        instance = engine.chromium.launch(**options)
        yield instance
        instance.close()


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('sheet,wrapper', [
    ('agent-fleet', '<main class="fleet-shell">'),
    ('knowledge-graph', '<main class="kg-shell">'),
    ('roles', '<main class="roles-page">'),
    ('spaces', '<main class="spaces-page">'),
    ('integrations', '<main class="integration-dialog">'),
    ('butler', '<main id="butler-panel">'),
    ('hfl-entry-editor', '<main class="entry-editor">'),
    ('hfl-timeline', '<main class="agenda-dialog">'),
    ('hfl-intent-reuse', '<main class="followups-board">'),
    ('corpus-workspaces', '<main class="corpus-advanced-panel">'),
    ('files', '<main id="files-app">'),
    ('share-activity', '<main class="share-graph-options">'),
    ('share-guest', '<main class="share-main-view">'),
    ('second-brain-hud', '<main class="hud-settings-menu">'),
])
def test_module_controls_use_one_visible_focus(browser, sheet, wrapper, width):
    page = browser.new_page(viewport={'width': width, 'height': 700})
    try:
        css = '\n'.join((ROOT / 'static/css' / f'{name}.css').read_text(encoding='utf-8')
                        for name in ('app.min', sheet, 'control-focus'))
        page.set_content(f'<style>{css}</style>{wrapper}'
                         '<button id="start">Start</button>'
                         '<select id="field"><option>A</option><option>B</option></select>'
                         '<button id="utility" class="focus-visible:ring-2 focus-visible:ring-violet-400">Open</button>'
                         '</main>')
        page.locator('#start').focus()
        page.keyboard.press('Tab')
        assert page.locator('#field').evaluate('e => e === document.activeElement')
        assert page.locator('#field').evaluate('''e => {
            const s=getComputedStyle(e);
            return [s.outlineWidth,s.outlineColor,s.outlineOffset,s.boxShadow];
        }''') == ['2px', 'rgb(56, 189, 248)', '-1px', 'none']
        page.keyboard.press('ArrowDown')
        assert page.locator('#field').input_value() == 'B'
        page.keyboard.press('Tab')
        assert page.locator('#utility').evaluate('e=>getComputedStyle(e).boxShadow') == 'none'
        assert page.locator('#utility').evaluate('e=>getComputedStyle(e).outlineWidth') == '2px'
        page.emulate_media(forced_colors='active')
        page.locator('#field').focus()
        assert page.locator('#field').evaluate('e=>getComputedStyle(e).outlineStyle') == 'solid'
    finally:
        page.close()


def test_transparent_checkbox_keeps_visible_focus(browser):
    page = browser.new_page()
    try:
        css = '\n'.join((ROOT / 'static/css' / f'{name}.css').read_text(encoding='utf-8')
                        for name in ('agent-fleet', 'roles', 'second-brain-hud', 'control-focus'))
        page.set_content(f'<style>{css}</style>'
                         '<div class="fleet-filter-types"><label id="fleet"><input type="checkbox">Actions</label></div>'
                         '<label class="role-archived-toggle"><input type="checkbox"><span id="role" class="role-toggle-track"></span></label>'
                         '<div class="hud-size-options"><label id="hud"><input type="radio" name="size">Small</label></div>')
        for selector in ('#fleet', '#role', '#hud'):
            page.keyboard.press('Tab')
            assert page.locator(selector).evaluate('e=>getComputedStyle(e).outlineWidth') == '2px'
            page.keyboard.press('Space')
            assert page.evaluate('document.activeElement.checked')
    finally:
        page.close()


@pytest.mark.parametrize('url', ['/login', '/home', '/manifesto', '/profile', '/second-brain'])
def test_page_serves_versioned_focus_asset(authenticated_client, url, browser, tmp_path):
    response = authenticated_client.get(url)
    assert response.status_code == 200
    match = re.search(r'/static/css/control-focus.css\?v=[0-9a-f]{12}', response.text)
    assert match, url
    assert authenticated_client.get(match[0]).status_code == 200
    # Render real server HTML/CSS without starting background data requests.
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    def asset(route):
        path = route.request.url.replace('http://focus.test', '')
        if path.startswith('/static/'):
            result = authenticated_client.get(path)
            route.fulfill(status=result.status_code, body=result.content,
                          content_type=result.headers.get('content-type'))
        else:
            route.abort()
    page.route('**/*', asset)
    try:
        for width in (390, 1440):
            page.set_viewport_size({'width': width, 'height': 1000})
            page.set_content('<base href="http://focus.test">' + response.text)
            if url == '/profile' and width == 390:
                save = page.locator('.profile-form-actions button[type=submit]').bounding_box()
                launch = page.locator('#butler-launch').bounding_box()
                assert save['y'] + save['height'] <= launch['y']
            page.screenshot(path=str(tmp_path / f'{url.strip("/")}-{width}.png'), full_page=True)
    finally:
        context.close()


def test_public_and_embedded_layout_assets(authenticated_client):
    from starlette.requests import Request
    from web import templates, share_asset
    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': [], 'query_string': b''})
    for name in ('share_base.html', 'modules/hfl_corpus/modal_base.html'):
        rendered = templates.env.get_template(name).render(request=request)
        assert re.search(r'control-focus.css\?v=[0-9a-f]{12}', rendered)
    response = authenticated_client.get(share_asset('css/control-focus.css'))
    assert response.status_code == 200
    assert 'text/css' in response.headers['content-type']
