"""Graph UI integration against isolated API data (requires installed Chromium/Edge)."""
import time
from pathlib import Path

import pytest


def test_saved_views_live_updates_and_full_graph(authenticated_client, monkeypatch, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities, graph_views
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'entities.sqlite3'))
    rows = [dict(id=str(i), text='Activity', title='Activity '+str(i), source='notes',
                 date='2026-09-01', tags=[], path='day.md', anchor=str(i), ref='', entities={})
            for i in range(5975)]
    monkeypatch.setattr(entities, 'current_entries', lambda: list(rows))
    with graph_views.connection() as db:
        db.execute('DELETE FROM graph_views')
        db.execute('DELETE FROM graph_view_last')
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            if Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe').exists():
                options['channel'] = 'msedge'
            else:
                pytest.skip('Install Playwright Chromium to run graph browser integration')
        browser = engine.chromium.launch(**options)
        try:
            errors, graph_requests = [], []

            def open_page():
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))

                def route_request(route):
                    request = route.request
                    if '/api/hfl/entities/graph?' in request.url:
                        graph_requests.append(request.url)
                    response = authenticated_client.request(request.method, request.url.replace('http://graph.test', ''),
                        content=request.post_data, headers={'content-type': request.headers.get('content-type', 'application/json')})
                    route.fulfill(status=response.status_code, body=response.content,
                                  headers={key: value for key, value in response.headers.items()
                                           if key.lower() not in {'content-encoding', 'content-length'}})

                page.route('http://graph.test/**', route_request)
                page.goto('http://graph.test/hfl-corpus/graph')
                page.wait_for_selector('#kg-workspace:not([inert])')
                return page

            page = open_page()
            assert page.locator('#kg-views-panel').is_hidden()
            page.click('#kg-open-views')
            assert page.locator('#kg-saved-views').is_visible()
            assert page.locator('#kg-open-views').get_attribute('aria-expanded') == 'true'
            page.keyboard.press('Escape')
            assert page.locator('#kg-views-panel').is_hidden()
            assert page.locator('#kg-open-views').evaluate('(el) => el === document.activeElement')
            page.select_option('#kg-density', '0')
            started = time.monotonic()
            page.wait_for_function("document.querySelector('#kg-status').textContent.includes('5977 / 5977')")
            page.wait_for_selector('canvas')
            print(f'Full graph response/render status: {time.monotonic()-started:.2f}s for 5,977 nodes')
            # Save a hidden type and a viewport change, then restore from a fresh browser context.
            page.click('#kg-legend button[data-kind="daily"]')
            page.click('#kg-in')
            page.once('dialog', lambda dialog: dialog.accept('Complete activity'))
            page.click('#kg-open-views')
            page.evaluate("""() => {
                const original = window.fetch;
                window.fetch = async (url, options) => {
                    if (url === '/api/hfl/graph-views' && options?.method === 'POST') {
                        await new Promise(resolve => window.releaseViewSave = resolve);
                    }
                    return original(url, options);
                };
            }""")
            page.click('#kg-save-as')
            page.wait_for_selector('#kg-save-feedback[data-state="saving"] .kg-save-spinner')
            assert page.locator('#kg-save').is_disabled()
            assert page.locator('#kg-save-as').is_disabled()
            assert page.locator('#kg-saved-views').is_disabled()
            page.click('#kg-open-views')
            assert page.locator('#kg-save-feedback').is_visible()
            page.screenshot(path=str(tmp_path / 'graph-saving.png'), full_page=True)
            page.evaluate('window.releaseViewSave()')
            page.wait_for_function("document.querySelector('#kg-dirty').textContent==='Saved'")
            assert page.locator('#kg-save-feedback').get_attribute('data-state') == 'success'
            assert 'Complete activity' in page.locator('#kg-save-feedback').inner_text()
            assert page.locator('#kg-save').is_enabled()
            first = authenticated_client.get('/api/hfl/graph-views').json()['views'][0]
            assert first['state']['density'] == '0'
            assert 'daily' not in first['state']['enabled']
            assert len(first['state']['layout']['positions']) == 5976
            page.context.close()
            second = open_page()
            # Wait past the old automatic-fit animation, then check the actual canvas viewport.
            second.wait_for_timeout(1200)
            def assert_saved_viewport():
                viewport = second.locator('#kg-canvas canvas').first.evaluate('''canvas => {
                    const {k,x,y} = canvas.__zoom;
                    return {zoom:k, x:(canvas.clientWidth/2-x)/k, y:(canvas.clientHeight/2-y)/k};
                }''')
                layout = first['state']['layout']
                assert viewport['zoom'] == pytest.approx(layout['zoom'], rel=1e-5)
                assert viewport['x'] == pytest.approx(layout['center']['x'], abs=0.1)
                assert viewport['y'] == pytest.approx(layout['center']['y'], abs=0.1)
            assert_saved_viewport()
            second.wait_for_function("document.querySelector('#kg-saved-views').selectedOptions[0].textContent==='Complete activity'")
            assert second.input_value('#kg-density') == '0'
            assert second.locator('#kg-legend button[data-kind="daily"]').get_attribute('aria-pressed') == 'false'
            # Leaving with local edits must not prompt or overwrite the saved profile.
            dialogs = []
            def accept_unexpected_dialog(dialog):
                dialogs.append(dialog.type)
                dialog.accept()
            second.on('dialog', accept_unexpected_dialog)
            second.click('#kg-legend button[data-kind="daily"]')
            assert second.locator('#kg-dirty').inner_text() == 'Unsaved changes'
            second.goto('about:blank')
            second.go_back()
            second.wait_for_selector('#kg-workspace:not([inert])')
            second.wait_for_function("document.querySelector('#kg-saved-views').selectedOptions[0].textContent==='Complete activity'")
            assert dialogs == []
            assert second.locator('#kg-dirty').inner_text() == ''
            assert second.locator('#kg-legend button[data-kind="daily"]').get_attribute('aria-pressed') == 'false'
            assert authenticated_client.get('/api/hfl/graph-views').json()['views'][0] == first
            # Keep the original tab idle; check additions and removals in the restored view.
            rows.append({**rows[0], 'id': 'new', 'title': 'New backend activity', 'anchor': 'new'})
            started = time.monotonic()
            second.wait_for_function("document.querySelector('#kg-status').textContent.includes('5977 / 5978')", timeout=30000)
            print(f'Live addition observed: {time.monotonic()-started:.2f}s')
            assert second.locator('#kg-legend button[data-kind="daily"]').get_attribute('aria-pressed') == 'false'
            rows.pop()
            second.wait_for_function("document.querySelector('#kg-status').textContent.includes('5976 / 5977')", timeout=30000)
            assert authenticated_client.get('/api/hfl/graph-views').json()['views'][0] == first
            assert_saved_viewport()
            assert second.locator('#kg-dirty').inner_text() == ''
            second.click('#kg-open-filters')
            second.select_option('#kg-rolling', '30')
            assert second.locator('#kg-since').is_disabled()
            second.click('#kg-filter')
            second.wait_for_selector('#kg-workspace:not([inert])')
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(graph_requests[-1]).query)
            assert params['rolling'] == ['30']
            from datetime import date
            assert (date.fromisoformat(params['until'][0]) - date.fromisoformat(params['since'][0])).days == 29
            second.click('#kg-open-views')
            second.click('#kg-save')
            second.wait_for_function("document.querySelector('#kg-dirty').textContent==='Saved'")
            saved = authenticated_client.get('/api/hfl/graph-views').json()['views'][0]
            assert saved['state']['rolling'] == 30
            # A rejected write must stop the spinner and allow a retry.
            second.route('**/api/hfl/graph-views/*', lambda route: route.fulfill(
                status=503, content_type='application/json', body='{"detail":"Please retry."}'))
            second.click('#kg-save')
            second.wait_for_selector('#kg-save-feedback[data-state="error"]')
            assert 'View not saved.' in second.locator('#kg-save-feedback').inner_text()
            assert second.locator('.kg-save-spinner').is_hidden()
            assert second.locator('#kg-save').is_enabled()
            second.unroute('**/api/hfl/graph-views/*')
            second.click('#kg-save')
            second.wait_for_selector('#kg-save-feedback[data-state="success"]')
            screenshot = tmp_path / 'graph-saved-views.png'
            second.screenshot(path=str(screenshot), full_page=True)
            print(f'Graph screenshot: {screenshot}')
            second.click('#kg-open-views')
            assert second.locator('#kg-views-panel').is_hidden()
            second.screenshot(path=str(tmp_path / 'graph-views-closed.png'), full_page=True)
            second.set_viewport_size({'width': 390, 'height': 844})
            second.click('#kg-open-views')
            panel = second.locator('#kg-views-panel').bounding_box()
            assert panel['x'] >= 0 and panel['x'] + panel['width'] <= 390
            second.screenshot(path=str(tmp_path / 'graph-views-mobile.png'), full_page=True)
            second.click('#kg-search')
            assert second.locator('#kg-views-panel').is_hidden()
            assert not errors, errors
        finally:
            browser.close()
