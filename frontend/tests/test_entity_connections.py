"""Connection lifecycle, owner identity, and shared browser controls."""
from dataclasses import replace
from pathlib import Path

import pytest

from modules.hfl_corpus import entities
from modules.profile.store import get_profile_store
from workflows.hfl.entity_store import get_store
from test_entity_soul import soul_data


def change(target='company', **kwargs):
    return dict(id='connection-1', target_id=target, relation='works_at', **kwargs)


def save(client, changes, identity='brian', versions=None):
    if versions is None:
        versions = client.get('/api/hfl/entities/connections/' + identity).json()['versions']
    return client.post('/api/hfl/entities/connections/' + identity, json={'changes': changes, 'versions': versions})


def test_connections_roundtrip_graph_and_incoming(soul_data, authenticated_client):
    client = authenticated_client
    assert save(client, [change()]).status_code == 200
    incoming = client.get('/api/hfl/entities/connections/company').json()['connections']
    assert len(incoming) == 1 and incoming[0]['incoming'] and incoming[0]['other_id'] == 'brian'
    graph = entities._corpus_graph(limit=0)
    assert any(e['source'] == 'brian' and e['target'] == 'company' for e in graph['edges'])
    filtered = entities._corpus_graph(since='2026-10-20', limit=0)
    assert not filtered['edges']
    assert save(client, [{**change(), 'id': 'duplicate'}]).status_code == 200
    assert len(client.get('/api/hfl/entities/connections/company').json()['connections']) == 1
    assert save(client, [change(source_id='brian', remove=True)], identity='company').status_code == 200
    assert not client.get('/api/hfl/entities/connections/company').json()['connections']


def test_connections_versions_validation_and_atomicity(soul_data, authenticated_client):
    client = authenticated_client
    assert save(client, [change()]).status_code == 200
    assert save(client, [change()], versions={'brian': 0}).status_code == 409
    assert save(client, [change(until='2026-01-01', since='2026-02-01')]).status_code == 422
    assert save(client, [change('brian')]).status_code == 409
    assert save(client, [change(remove=True), change('missing')]).status_code == 409
    assert len(client.get('/api/hfl/entities/connections/brian').json()['connections']) == 1


def test_symmetric_connections_are_not_duplicated_from_other_endpoint(soul_data, authenticated_client):
    assert save(authenticated_client, [{**change(), 'relation':'related_to'}]).status_code == 200
    assert save(authenticated_client, [{**change('brian'), 'id':'reverse', 'relation':'related_to'}], identity='company').status_code == 200
    links = authenticated_client.get('/api/hfl/entities/connections/brian').json()['connections']
    assert len(links) == 1


def test_manual_activity_link_preserves_original_and_filters(soul_data, authenticated_client):
    rows, _ = soul_data
    original = dict(rows[0])
    assert save(authenticated_client, [change('entry-one', activity=True)]).status_code == 200
    entry = next(e for e in entities.entity_index() if e['id'] == 'brian')['entries'][0]
    assert entry['method'] == 'user-confirmed' and rows[0] == original
    graph = entities._corpus_graph(limit=0)
    assert any(e['source'] == 'entry:entry-one' and e['target'] == 'brian' for e in graph['edges'])
    assert not entities._corpus_graph(source='other', limit=0)['edges']
    assert save(authenticated_client, [change('entry-one', activity=True, remove=True)]).status_code == 200
    assert not next(e for e in entities.entity_index() if e['id'] == 'brian')['entries']


def test_owner_reuses_identity_and_renames_without_losing_links(soul_data, authenticated_client):
    store = get_profile_store()
    store.save(replace(store.get(), first_name='Brian', last_name='Bartilet'))
    rows = entities.entity_index()
    assert [e['id'] for e in rows if e['is_owner']] == ['brian']
    assert save(authenticated_client, [change()]).status_code == 200
    store.save(replace(store.get(), first_name='Bryan'))
    owner = next(e for e in entities.entity_index() if e['is_owner'])
    assert owner['id'] == 'brian' and owner['label'] == 'Bryan Bartilet'
    assert len(authenticated_client.get('/api/hfl/entities/connections/brian').json()['connections']) == 1
    assert authenticated_client.post('/api/hfl/entities/type/brian', json={'kind':'companies'}).status_code == 409


def test_owner_ambiguous_binding_and_empty_corpus(soul_data, authenticated_client):
    store = get_profile_store()
    store.save(replace(store.get(), first_name='Brian', last_name='Bartilet'))
    get_store().save_profile('other', 'people', {'name':'Brian Bartilet'})
    rows = entities.entity_index()
    assert not any(e['is_owner'] for e in rows)
    assert {e['id'] for e in rows if e['owner_candidate']} == {'brian','other'}
    assert authenticated_client.post('/api/hfl/entities/owner-binding', json={'identity':'brian'}).status_code == 200
    assert next(e['id'] for e in entities.entity_index() if e['is_owner']) == 'brian'


def test_manual_creation_and_owner_without_activity(soul_data, authenticated_client):
    soul_data[0].clear()
    store = get_profile_store()
    store.save(replace(store.get(), first_name='New', last_name='Owner'))
    owner = next(e for e in entities.entity_index() if e['is_owner'])
    again = next(e for e in entities.entity_index() if e['is_owner'])
    assert owner['id'] == again['id'] and not owner['entries']
    created = authenticated_client.post('/api/hfl/entities/create', json={'name':'New organization','kind':'companies'}).json()['id']
    assert save(authenticated_client, [change(created)], identity=owner['id']).status_code == 200
    graph = entities._corpus_graph(limit=0)
    assert {owner['id'], created}.issubset({n['id'] for n in graph['nodes']})
    assert any(e['source'] == owner['id'] and e['target'] == created for e in graph['edges'])


def test_connections_require_authentication():
    from fastapi.testclient import TestClient
    from hfl_api import app
    client = TestClient(app)
    for path in ('connections/brian', 'connection-activities'):
        assert client.get('/api/hfl/entities/' + path).status_code in (401, 403)
    assert client.post('/api/hfl/entities/connections/brian', json={'versions':{},'changes':[]}).status_code in (401,403)


def test_owner_and_activity_links_follow_merge_and_undo(soul_data, authenticated_client):
    profiles = get_profile_store()
    profiles.save(replace(profiles.get(), first_name='Brian', last_name='Bartilet'))
    entities.entity_index()
    assert save(authenticated_client, [change('entry-one', activity=True)]).status_code == 200
    store = get_store()
    store.save_profile('canonical', 'people', {'name':'Brian canonical'})
    decision = store.merge('brian', 'canonical', 'test confirmation')
    assert next(e['id'] for e in entities.entity_index() if e['is_owner']) == 'canonical'
    assert save(authenticated_client, [change('entry-one', activity=True, remove=True)], identity='canonical').status_code == 200
    assert not authenticated_client.get('/api/hfl/entities/connections/canonical').json()['connections']
    store.undo(decision)
    assert next(e['id'] for e in entities.entity_index() if e['is_owner']) == 'brian'


@pytest.mark.parametrize('width', [1440, 390])
def test_connection_picker_browser(soul_data, authenticated_client, tmp_path, width):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, **({} if Path(engine.chromium.executable_path).exists() else {'channel':'msedge'}))
        try:
            page = browser.new_page(viewport={'width':width,'height':1000})
            page.set_default_timeout(10000)
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            def route_request(route):
                req = route.request
                response = authenticated_client.request(req.method, req.url.replace('https://entities.test',''), content=req.post_data_buffer, headers={'content-type':req.headers.get('content-type','application/json')})
                route.fulfill(status=response.status_code, body=response.content, headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            card = page.locator('[data-entity-id="brian"]'); card.locator(':scope > summary').click()
            assert not card.get_by_text('Supporting activity', exact=True).evaluate('n=>n.parentElement.open')
            card.get_by_role('button', name='Update soul', exact=True).click()
            dialog = page.get_by_role('dialog', name='Brian Bartilet')
            playwright.expect(dialog.locator('form > details[open]')).to_have_count(0)
            dialog.get_by_text('Connections', exact=True).click()
            playwright.expect(dialog.get_by_label('Entity type', exact=True)).to_have_value('')
            playwright.expect(dialog.get_by_role('button', name='Acme organizations')).to_be_visible()
            dialog.get_by_label('Entity type', exact=True).select_option('companies')
            dialog.get_by_role('button', name='Acme organizations').click()
            playwright.expect(dialog.get_by_label('Relationship', exact=True)).not_to_be_visible()
            dialog.get_by_role('button', name='Edit', exact=True).click()
            dialog.get_by_label('Relationship', exact=True).select_option('works_at')
            dialog.get_by_label('Find an entity or activity').click()
            playwright.expect(dialog.get_by_label('Relationship', exact=True)).not_to_be_visible()
            dialog.get_by_label('Entity type', exact=True).select_option('people')
            playwright.expect(dialog.get_by_text('Not saved', exact=True)).to_be_visible()
            dialog.get_by_role('button', name='Save', exact=True).click()
            playwright.expect(dialog.get_by_text('Soul saved.',exact=True)).to_be_visible()
            dialog.get_by_text('Connections', exact=True).click()
            playwright.expect(dialog.get_by_role('button', name='Remove', exact=True)).to_be_visible()
            # Existing edits remain local when clicking outside; Save is the only write.
            dialog.get_by_role('button', name='Edit', exact=True).click()
            dialog.get_by_label('Relationship', exact=True).select_option('member_of')
            dialog.get_by_label('Basis or supporting activity link (optional)').fill('Confirmed membership')
            dialog.get_by_label('Find an entity or activity').click()
            playwright.expect(dialog.get_by_label('Relationship', exact=True)).not_to_be_visible()
            current = authenticated_client.get('/api/hfl/entities/soul-editor/brian').json()
            assert current['connections'][0]['relation'] == 'works_at'
            dialog.get_by_role('button', name='Save', exact=True).click()
            playwright.expect(dialog.get_by_text('Soul saved.', exact=True)).to_be_visible()
            dialog.get_by_text('Connections', exact=True).click()
            current = authenticated_client.get('/api/hfl/entities/soul-editor/brian').json()
            assert current['connections'][0]['relation'] == 'member_of'
            assert current['connections'][0]['evidence'] == 'Confirmed membership'
            assert dialog.evaluate('n=>n.scrollWidth<=n.clientWidth')
            path = Path('results') / f'entity-connections-{width}.png'; path.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(path))
            dialog.get_by_label('Connect to', exact=True).select_option('activity')
            dialog.get_by_role('button', name='Work log entries').click()
            dialog.get_by_role('button', name='Save', exact=True).click()
            playwright.expect(dialog.get_by_text('Soul saved.',exact=True)).to_be_visible()
            dialog.get_by_text('Connections', exact=True).click()
            playwright.expect(dialog.get_by_role('button', name='Remove', exact=True)).to_have_count(2)
            dialog.get_by_role('button', name='Close', exact=True).click()
            # Exercise the same editor from the graph and its visible-neighbor refresh.
            page.goto('https://entities.test/hfl-corpus/graph?source=notes&select=brian')
            page.locator('#kg-detail').get_by_role('button', name='Update soul', exact=True).click()
            graph_dialog = page.get_by_role('dialog', name='Brian Bartilet')
            graph_dialog.get_by_text('Connections', exact=True).click()
            graph_dialog.get_by_label('Entity type', exact=True).select_option('companies')
            graph_dialog.get_by_label('Find an entity or activity').fill('New Team')
            graph_dialog.get_by_role('button', name='Create “New Team”', exact=True).click()
            graph_dialog.get_by_role('button', name='Save', exact=True).click()
            playwright.expect(graph_dialog.get_by_text('Soul saved.',exact=True)).to_be_visible()
            graph_dialog.get_by_text('Connections', exact=True).click()
            playwright.expect(graph_dialog.locator('.connection-current strong').filter(has_text='New Team')).to_be_visible()
            graph_dialog.get_by_role('button', name='Close', exact=True).click()
            reveal = page.locator('#kg-detail').get_by_role('button', name='Show connected entities', exact=True)
            playwright.expect(reveal).to_be_visible()
            reveal.click()
            playwright.expect(page.locator('#kg-detail')).to_contain_text('3 visible connections')
            page.screenshot(path=str(Path('results') / f'entity-connections-graph-{width}.png'))
            assert not errors
        except Exception:
            print('BROWSER ERRORS:', errors)
            Path('results/connection-page-state.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
            page.screenshot(path=str(Path('results') / f'entity-connections-failure-{width}.png'))
            raise
        finally:
            browser.close()
