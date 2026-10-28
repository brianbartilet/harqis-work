"""Entity maturity filters affect graph nodes, edges, capacity and saved browser state."""
import pytest

from modules.hfl_corpus import entities
from workflows.hfl.entity_store import get_store
from test_entity_signal import corpus  # noqa: F401
from test_graph_capacity import launch, route_app, sample_graph


@pytest.mark.parametrize('guard', [False, True])
def test_graph_maturity_preserves_activities_and_filters_before_capacity(corpus, authenticated_client, guard):
    store = get_store()
    mention = entities.mention(corpus[0], 'tools', 'Python', 'Python', 'model-extracted')
    store.save('one', entities.entry_hash(corpus[0]), [mention])
    params = dict(limit=0, capacity_guard=guard, include_provisional=False)
    url = '/api/hfl/entities/graph'
    hidden = authenticated_client.get(url, params=params).json()
    assert mention['id'] not in {n['id'] for n in hidden['nodes']}
    assert 'entry:one' in {n['id'] for n in hidden['nodes']}
    assert all(e['target'] != mention['id'] for e in hidden['edges'])
    shown = authenticated_client.get(url, params={**params, 'include_provisional': True}).json()
    assert mention['id'] in {n['id'] for n in shown['nodes']}
    assert shown['total_nodes'] == hidden['total_nodes'] + 1
    if guard:
        assert shown['capacity']['total_nodes'] == hidden['capacity']['total_nodes'] + 1
    corpus.append({**corpus[0], 'id': 'two'})
    store.save('two', entities.entry_hash(corpus[1]), [mention])
    assert mention['id'] in {n['id'] for n in authenticated_client.get(url, params=params).json()['nodes']}
    corpus.pop()
    store.save_profile(mention['id'], 'tools', {'name': 'Python'})
    assert mention['id'] in {n['id'] for n in authenticated_client.get(url, params=params).json()['nodes']}


@pytest.mark.parametrize('width', [1440, 390])
def test_graph_maturity_filter_persists(authenticated_client, monkeypatch, tmp_path, width):
    pw = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr(entities, 'graph', lambda *args: sample_graph(12 if args[-1] else 10))
    with pw.sync_playwright() as engine:
        browser = launch(engine)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda r: requests.append(r.url) if '/entities/graph?' in r.url else None)
            route_app(page, authenticated_client)
            page.goto('http://graph.test/hfl-corpus/graph')
            page.click('#kg-open-filters')
            pw.expect(page.locator('#kg-maturity')).to_have_value('')
            assert any('include_provisional=false' in url for url in requests)
            page.select_option('#kg-maturity', 'all')
            page.screenshot(path=str(tmp_path / f'graph-maturity-{width}.png'))
            assert page.locator('#kg-filter-drawer').evaluate('(el)=>el.scrollWidth <= el.clientWidth')
            page.click('#kg-filter')
            page.wait_for_function("Object.keys(localStorage).some(k=>k.startsWith('hfl:graph:state:') && JSON.parse(localStorage[k]).filters.maturity==='all')")
            assert any('include_provisional=true' in url for url in requests)
            page.reload()
            page.click('#kg-open-filters')
            pw.expect(page.locator('#kg-maturity')).to_have_value('all')
            assert not errors
        finally:
            browser.close()
