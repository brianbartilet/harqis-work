"""The live graph palette follows the configured vocabulary."""
from pathlib import Path

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_types
from workflows.hfl.entity_store import get_store
from test_corpus_entities import corpus  # noqa: F401


@pytest.mark.parametrize('capacity', [False, True])
def test_graph_exposes_current_type_colors(corpus, authenticated_client, capacity):
    entity_types.update('people', 'Contacts', '#112233', 'Named people')
    entity_types.create('Games', '#abcdef', 'Named games')
    data = authenticated_client.get('/api/hfl/entities/graph', params={'capacity_guard': capacity}).json()
    types = {t['id']: t for t in data['types']}
    assert types['people'] == dict(id='people', name='Contacts', color='#112233')
    assert types['games']['color'] == '#abcdef'
    assert types['pets']['color'] == '#f9a8d4'
    assert all('description' not in t for t in data['types'])


@pytest.mark.parametrize('width', [1440, 390])
def test_graph_palette_browser_refresh(corpus, authenticated_client, tmp_path, width):
    pw = pytest.importorskip('playwright.sync_api')
    entity_types.update('people', 'Contacts', '#112233', 'Named people')
    entity_types.create('Games', '#abcdef', 'Named games')
    row = corpus[0]
    get_store().save(row['id'], entities.entry_hash(row), [
        entities.mention(row, kind, label, label, 'test')
        for kind, label in [('people', 'Alex'), ('games', 'Chess'), ('pets', 'Fido')]])
    with pw.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists(): options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            def route_request(route):
                req = route.request
                response = authenticated_client.request(req.method, req.url.replace('http://graph.test', ''), content=req.post_data)
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://graph.test/**', route_request)
            page.goto('http://graph.test/hfl-corpus/graph?since=2026-09-01&until=2026-09-01')
            page.wait_for_selector('#kg-workspace:not([inert])')
            for kind, color, rgb in [('people', '#112233', 'rgb(17, 34, 51)'), ('games', '#abcdef', 'rgb(171, 205, 239)'), ('pets', '#f9a8d4', 'rgb(249, 168, 212)')]:
                pw.expect(page.locator(f'#kg-legend [data-kind="{kind}"] .kg-dot')).to_have_css('background-color', rgb)
                assert page.evaluate('(kind) => HflGraphAppearance.color(kind)', kind) == color
            assert page.evaluate('HflGraphAppearance.color("entries")') == '#77dcf5'
            pw.expect(page.locator('#kg-legend [data-kind="people"]')).to_contain_text('contacts')
            entity_types.update('people', 'People', '#445566', 'Named people')
            page.reload()
            pw.expect(page.locator('#kg-legend [data-kind="people"] .kg-dot')).to_have_css('background-color', 'rgb(68, 85, 102)')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / f'graph-colors-{width}.png'))
            assert not errors
        finally:
            browser.close()
