"""Main graph capacity contract, recovery, and opt-in renderer measurements."""
import json
import os
from pathlib import Path
import time

import pytest
from test_corpus_entities import corpus, entry
from test_hfl_ideas import ideas, payload


def sample_graph(count=1200, degree=4):
    hubs = min(20, count)
    nodes = [dict(id=f'sources:{i}', kind='sources', label=f'Source {i}') for i in range(hubs)]
    nodes += [dict(id=f'entry:{i}', kind='entries', label=f'Activity {i}', date='2026-10-01', source='notes') for i in range(count-hubs)]
    edges = [dict(source=n['id'], target=nodes[j % hubs]['id'], relation='mentions')
             for n in nodes[hubs:] for j in range(degree)]
    return dict(nodes=nodes, edges=edges, total_nodes=count, sources=['notes'])


def test_capacity_api_bounds_and_opt_in(authenticated_client, monkeypatch):
    from modules.hfl_corpus import entities
    graph = sample_graph()
    monkeypatch.setattr(entities, 'graph', lambda *args: graph)
    url = '/api/hfl/entities/graph'
    assert len(authenticated_client.get(url).json()['nodes']) == 1200
    response = authenticated_client.get(url, params={'capacity_guard': True}).json()
    assert response['nodes'] == response['edges'] == []
    assert response['capacity']['total_nodes'] == 1200
    assert response['capacity']['total_edges'] == 4720
    response = authenticated_client.get(url, params={'capacity_guard': True, 'preview': True}).json()
    assert len(response['nodes']) == 1000
    assert 0 < len(response['edges']) <= 2000
    ids = {n['id'] for n in response['nodes']}
    assert all(e['source'] in ids and e['target'] in ids for e in response['edges'])
    assert response['capacity']['preview'] and response['truncated']
    assert authenticated_client.get(url, params={'node_limit': 10001}).status_code == 422
    assert authenticated_client.get(url, params={'node_limit': 999}).status_code == 422
    assert authenticated_client.get(url, params={'edge_limit': 5001}).status_code == 422
    assert not authenticated_client.get(url, params={'capacity_guard': True, 'node_limit': 10000, 'edge_limit': 5000}).json()['capacity']['exceeded']
    assert authenticated_client.get(url, params={'edge_limit': 0}).status_code == 422


def test_connection_budget_and_exact_boundary(authenticated_client, monkeypatch):
    from modules.hfl_corpus import entities
    graph = sample_graph(1000, 4)
    monkeypatch.setattr(entities, 'graph', lambda *args: graph)
    params = dict(capacity_guard=True, node_limit=1000, edge_limit=3920)
    url = '/api/hfl/entities/graph'
    assert not authenticated_client.get(url, params=params).json()['capacity']['exceeded']
    params['edge_limit'] = 3919
    assert authenticated_client.get(url, params=params).json()['capacity']['exceeded']
    params['preview'] = True
    assert len(authenticated_client.get(url, params=params).json()['edges']) == 3919


def test_capacity_uses_filtered_canonical_graph(corpus, authenticated_client):
    corpus.extend(entry(str(i), source='meetings') for i in range(1100))
    url = '/api/hfl/entities/graph'
    blocked = authenticated_client.get(url, params={'capacity_guard': True, 'node_limit': 1000}).json()
    assert blocked['capacity']['exceeded']
    filtered = authenticated_client.get(url, params={'capacity_guard': True, 'source': 'notes'}).json()
    assert not filtered['capacity']['exceeded']
    assert filtered['capacity']['total_nodes'] == len(filtered['nodes']) == 3
    empty = authenticated_client.get(url, params={'capacity_guard': True, 'query': 'no matching label'}).json()
    assert not empty['capacity']['exceeded'] and empty['nodes'] == []


def test_capacity_includes_saved_intents(ideas, authenticated_client):
    for i in range(101):
        ideas.save_idea(payload(title=f'Intent {i}'), 'owner')
    response = authenticated_client.get('/api/hfl/entities/graph', params={'capacity_guard': True, 'node_limit': 1000}).json()
    assert not response['capacity']['exceeded']
    assert response['capacity']['total_nodes'] >= 101
    assert len(response['nodes']) == response['capacity']['total_nodes']


def launch(engine):
    options = {'headless': True}
    if not Path(engine.chromium.executable_path).exists():
        options['channel'] = 'msedge'
    return engine.chromium.launch(**options)


def route_app(page, client):
    def handle(route):
        request = route.request
        response = client.request(request.method, request.url.replace('http://graph.test', ''), content=request.post_data,
                                  headers={k: v for k, v in request.headers.items() if k in {'content-type', 'x-csrf-token'}})
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k: v for k, v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}})
    page.route('http://graph.test/**', handle)


@pytest.mark.parametrize('width', [1440, 390])
def test_capacity_browser_recovery(authenticated_client, monkeypatch, width):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    monkeypatch.setattr(entities, 'graph', lambda *args: sample_graph(30 if args[4] == 'narrow' else 1200))
    with playwright.sync_playwright() as engine:
        browser = launch(engine)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000 if width > 500 else 844})
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url) if '/entities/graph?' in request.url else None)
            route_app(page, authenticated_client)
            page.goto('http://graph.test/hfl-corpus/graph')
            overlay = page.locator('#kg-capacity-overlay')
            playwright.expect(overlay).to_be_visible()
            playwright.expect(page.locator('#kg-capacity-message')).to_contain_text('1,200')
            assert page.locator('#kg-canvas').evaluate('(el)=>el.inert')
            before = len(requests)
            page.wait_for_timeout(3500)
            assert len(requests) == before
            page.screenshot(path=f'results/activity-graph-capacity-{width}.png')
            box = overlay.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
            page.click('#kg-capacity-filters')
            page.fill('#kg-node-limit', '1100')
            page.fill('#kg-edge-limit', '1000')
            page.click('#kg-filter')
            playwright.expect(page.locator('#kg-capacity-message')).to_contain_text('1,100 nodes')
            page.click('#kg-capacity-preview')
            playwright.expect(overlay).to_be_hidden()
            playwright.expect(page.locator('#kg-capacity-preview-note')).to_contain_text('1,100 of 1,200')
            page.screenshot(path=f'results/activity-graph-preview-{width}.png')
            page.reload()
            playwright.expect(overlay).to_be_visible()
            page.click('#kg-capacity-filters')
            assert page.input_value('#kg-node-limit') == '1100'
            page.click('#kg-capacity-reset')
            assert page.input_value('#kg-node-limit') == '1000'
            page.click('#kg-filter')
            playwright.expect(overlay).to_be_visible()
            page.click('#kg-capacity-search')
            playwright.expect(page.locator('#kg-search')).to_be_focused()
            page.fill('#kg-search', 'narrow')
            playwright.expect(overlay).to_be_hidden()
            playwright.expect(page.locator('#kg-map-count')).to_contain_text('30 nodes')
            assert page.locator('#kg-capacity-preview-note').is_hidden()
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize('suffix', ['?embed=1', '?readonly=1'])
def test_capacity_excludes_previews(authenticated_client, monkeypatch, suffix):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    monkeypatch.setattr(entities, 'graph', lambda *args: sample_graph(30))
    with playwright.sync_playwright() as engine:
        browser = launch(engine)
        try:
            page = browser.new_page()
            requests = []
            page.on('request', lambda request: requests.append(request.url) if '/entities/graph?' in request.url else None)
            route_app(page, authenticated_client)
            page.goto('http://graph.test/hfl-corpus/graph' + suffix)
            page.wait_for_selector('#kg-workspace:not([inert])')
            assert requests and all('capacity_guard' not in url for url in requests)
            assert page.locator('#kg-capacity-settings').is_hidden()
        finally:
            browser.close()


def test_background_growth_and_failed_retry(authenticated_client, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    current = {'count': 30}
    monkeypatch.setattr(entities, 'graph', lambda *args: sample_graph(current['count']))
    with playwright.sync_playwright() as engine:
        browser = launch(engine)
        try:
            page = browser.new_page()
            route_app(page, authenticated_client)
            page.goto('http://graph.test/hfl-corpus/graph')
            playwright.expect(page.locator('#kg-map-count')).to_contain_text('30 nodes')
            page.click('#kg-fullscreen')
            current['count'] = 1200
            playwright.expect(page.locator('#kg-capacity-overlay')).to_be_visible(timeout=15000)
            assert page.locator('#kg-canvas').evaluate('(el)=>el.inert')
            page.click('#kg-capacity-filters')
            assert not page.locator('.kg-shell').evaluate("el=>el.classList.contains('kg-fullscreen')")
            page.click('#kg-close-filters')
            page.route('**/api/hfl/entities/graph?**', lambda route: route.fulfill(status=503, body='Unavailable'))
            page.click('#kg-capacity-preview')
            playwright.expect(page.locator('#kg-status')).to_contain_text('could not load')
            assert page.locator('#kg-reload').is_enabled()
            page.unroute('**/api/hfl/entities/graph?**')
            current['count'] = 30
            page.click('#kg-reload')
            playwright.expect(page.locator('#kg-map-count')).to_contain_text('30 nodes')
            assert page.locator('#kg-capacity-overlay').is_hidden()
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_filter_controls_week_and_capacity_migration(authenticated_client, monkeypatch, width):
    from urllib.parse import urlsplit, parse_qs
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    monkeypatch.setattr(entities, 'graph', lambda *args: sample_graph(30))
    with playwright.sync_playwright() as engine:
        browser = launch(engine)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900}, timezone_id='Asia/Singapore')
            page.add_init_script('''if (!localStorage.getItem('capacity-test-seeded')) {
                localStorage.setItem('hfl:graph:capacity:v1:frontend-test-user',JSON.stringify({nodes:500,edges:2000}));
                localStorage.setItem('capacity-test-seeded','true');
            }''')
            # Sunday locally: the date range must not slip into Monday in UTC.
            page.clock.set_fixed_time('2026-10-25T10:00:00+08:00')
            requests, errors = [], []
            page.on('request', lambda r: requests.append(parse_qs(urlsplit(r.url).query)) if '/entities/graph?' in r.url else None)
            page.on('pageerror', lambda e: errors.append(str(e)))
            route_app(page, authenticated_client)
            page.goto('http://graph.test/hfl-corpus/graph')
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-open-filters')
            assert page.input_value('#kg-node-limit') == '1000'
            assert page.input_value('#kg-edge-limit') == '2000'
            assert page.get_by_role('switch', name='Shared connections only').count() == 1
            page.get_by_role('switch', name='Shared connections only').check()
            assert page.get_by_role('button', name='Decrease maximum nodes by 100').is_disabled()
            page.get_by_role('button', name='Increase maximum nodes by 100').click()
            assert page.input_value('#kg-node-limit') == '1100'
            page.fill('#kg-node-limit', '10000')
            assert page.get_by_role('button', name='Increase maximum nodes by 100').is_disabled()
            page.get_by_role('button', name='Decrease maximum nodes by 100').click()
            assert page.input_value('#kg-node-limit') == '9900'
            page.fill('#kg-node-limit', '10001')
            page.click('#kg-filter')
            assert page.locator('#kg-filter-drawer').is_visible()
            assert not page.locator('#kg-node-limit').evaluate('el=>el.validity.valid')
            page.click('#kg-capacity-reset')
            assert page.input_value('#kg-node-limit') == '1000'
            assert page.input_value('#kg-edge-limit') == '2000'
            page.select_option('#kg-rolling', 'week')
            assert page.input_value('#kg-since') == '2026-10-19'
            assert page.input_value('#kg-until') == '2026-10-25'
            page.locator('#kg-capacity-settings').scroll_into_view_if_needed()
            page.screenshot(path=f'results/activity-graph-filters-{width}.png')
            page.click('#kg-capacity-help-open')
            help_dialog = page.locator('#kg-capacity-help')
            playwright.expect(help_dialog).to_be_visible()
            playwright.expect(help_dialog).to_contain_text('time and memory')
            page.screenshot(path=f'results/activity-graph-help-{width}.png')
            box=help_dialog.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            page.keyboard.press('Escape')
            playwright.expect(help_dialog).to_be_hidden()
            playwright.expect(page.locator('#kg-capacity-help-open')).to_be_focused()
            assert page.locator('#kg-filter-drawer').is_visible()
            page.click('#kg-filter')
            page.wait_for_selector('#kg-workspace:not([inert])')
            assert requests[-1]['since'] == ['2026-10-19'] and requests[-1]['until'] == ['2026-10-25']
            assert requests[-1]['shared'] == ['true']
            page.wait_for_timeout(600)  # Existing view-state persistence debounce.
            page.reload()
            page.wait_for_selector('#kg-workspace:not([inert])')
            page.click('#kg-open-filters')
            assert page.input_value('#kg-rolling') == 'week'
            assert page.locator('#kg-shared').is_checked()
            page.click('#kg-close-filters')
            page.clock.set_fixed_time('2026-10-26T00:05:00+08:00')
            page.wait_for_function("document.querySelector('#kg-since').value==='2026-10-26'", timeout=15000)
            assert requests[-1]['since'] == ['2026-10-26'] and requests[-1]['until'] == ['2026-10-26']
            assert not errors
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get('GRAPH_CAPACITY_BENCHMARK'), reason='Opt-in renderer benchmark')
def test_capacity_measurements(authenticated_client, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import entities
    measurements = []
    with playwright.sync_playwright() as engine:
        browser = launch(engine)
        try:
            for width in [1440, 390]:
                for count, degree in [(500, 4), (1000, 4), (2000, 4), (3000, 4), (6000, 4), (1000, 12)]:
                    graph = sample_graph(count, degree)
                    monkeypatch.setattr(entities, 'graph', lambda *args: graph)
                    page = browser.new_page(viewport={'width': width, 'height': 1000 if width > 500 else 844})
                    route_app(page, authenticated_client)
                    # Excluded embedded renderer permits measuring above the guard.
                    started = time.perf_counter()
                    page.goto('http://graph.test/hfl-corpus/graph?embed=1')
                    page.wait_for_function("document.querySelector('#kg-map-count').textContent.includes('nodes')")
                    load_ms = (time.perf_counter()-started)*1000
                    page.click('#kg-open-animation')
                    page.click('[data-animation="drift"]')
                    frames = page.evaluate('''() => new Promise(resolve => {
                        const deltas=[];let previous=performance.now(),start=previous;
                        function frame(now){deltas.push(now-previous);previous=now;
                            if(now-start<2000)requestAnimationFrame(frame);
                            else resolve(deltas.sort((a,b)=>a-b));}
                        requestAnimationFrame(frame);
                    })''')
                    measurements.append(dict(width=width, nodes=count, edges=len(graph['edges']),
                                             payload_bytes=len(json.dumps(graph).encode()), load_ms=round(load_ms),
                                             frame_p95_ms=round(frames[int(len(frames)*.95)], 1), max_frame_ms=round(max(frames), 1)))
                    page.close()
        finally:
            browser.close()
    Path('results/graph-capacity-measurements.json').write_text(json.dumps(measurements, indent=2))
    print(json.dumps(measurements))
