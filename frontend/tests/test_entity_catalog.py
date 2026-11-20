import base64
import json
import pytest
from frontend.tests.test_agent_fleet import fleet, bridge
from frontend.tests.test_grokbot_connector import grok, bots, USER
from modules.agents import entity_catalog as catalog, ecosystem, entities
from modules.integrations import grokbot_outputs


def test_type_mappings_are_owner_scoped_and_explicit(fleet):
    types = catalog.definitions('alice')
    assert catalog.normalize(types, 'nod', 'schedules', 'trigger') == 'schedule'
    assert catalog.normalize(types, 'grokbot', 'skills', 'configuration') == 'skill'
    assert catalog.normalize(types, 'unknown', 'skills', 'configuration') == 'configuration'
    custom = catalog.save('alice', dict(id='document', name='Document', description='Saved documents', color='#abcdef', keywords=['document'], equivalents=[]))
    files = types['file']
    mapping = next(m for m in files['equivalents'] if m['source_object'] == 'library files')
    with pytest.raises(ValueError, match='already maps'):
        catalog.save('alice', {**custom, 'equivalents': [mapping]})
    catalog.save('alice', {**files, 'equivalents': [m for m in files['equivalents'] if m != mapping]})
    catalog.save('alice', {**custom, 'equivalents': [mapping]})
    assert catalog.normalize(catalog.definitions('alice'), 'grokbot', 'library files', 'file') == 'document'
    assert catalog.normalize(catalog.definitions('bob'), 'grokbot', 'library files', 'file') == 'file'
    with pytest.raises(ValueError, match='changed'):
        catalog.save('alice', custom)
    with pytest.raises(ValueError, match='Reassign'):
        catalog.remove('alice', 'document')
    with pytest.raises(ValueError, match='Built-in'):
        catalog.remove('alice', 'skill')
    catalog.remove('alice', 'document', 'file')
    assert catalog.normalize(catalog.definitions('alice'), 'grokbot', 'library files', 'entry') == 'file'
    assert 'document' not in catalog.definitions('alice')


def test_skill_projection_and_catalog_keep_stable_ids(fleet, bridge):
    import socket
    from modules.hfl_corpus.action_agents import store as terminals
    terminals().advertise(socket.gethostname(), [{'id':'hermes', 'name':'Hermes', 'available':True, 'reason':''}])
    agent = fleet.initialize().save({**fleet.defaults('Skills agent'), 'skills': ['upload:test.md']})
    before = ecosystem.graph(USER)
    skill = next(n for n in before['nodes'] if n['id'] == 'skills:upload:test.md')
    assert skill['kind'] == 'skill' and agent['id'] in skill['agent_ids']
    definition = catalog.definitions(USER)['skill']
    catalog.save(USER, {**definition, 'name': 'Expertise', 'color': '#123456'})
    after = ecosystem.graph(USER)
    assert next(n for n in after['nodes'] if n['id'] == skill['id'])['color'] == '#123456'
    assert next(t for t in after['types'] if t['id'] == 'skill')['name'] == 'Expertise'


def test_mapping_applies_to_every_agent_of_type_without_merging(fleet, bridge):
    agents = [fleet.initialize().save({**fleet.defaults(name), 'runtime': runtime})
              for name, runtime in [('One', 'nod'), ('Two', 'nod'), ('Other', 'hermes')]]
    custom = dict(id='routine', name='Routine', description='Reusable routine', color='#abcdef',
                  keywords=['routine'], equivalents=[dict(agent_type='nod', source_object='routines')])
    catalog.save(USER, custom)
    recorded = [ecosystem.record(USER, dict(id=a['id'] + ':routine', source='test-import', agent_id=a['id'],
                kind='workflow', label='Morning routine', source_object='routines')) for a in agents]
    graph = ecosystem.graph(USER)
    nodes = {n['id']: n for n in graph['nodes']}
    assert [nodes[r['id']]['kind'] for r in recorded] == ['routine', 'routine', 'workflow']
    assert len({r['id'] for r in recorded}) == 3
    with fleet.store().connect() as db:
        assert {json.loads(r[0])['kind'] for r in db.execute('SELECT payload FROM fleet_objects WHERE user=?', (USER,))} == {'workflow'}


def test_cleanup_preserves_history_links_and_other_owners(fleet):
    fleet.initialize()
    with entities.connection() as db:
        for owner, key, value in [('alice', 'blank', {}), ('alice', 'linked', {}), ('alice', 'stale', {'state':'stale'}), ('bob', 'blank', {})]:
            db.execute('INSERT INTO fleet_entities VALUES (?,?,?)', (owner, key, json.dumps(value)))
        db.execute('INSERT INTO fleet_entity_edges VALUES (?,?,?,?)', ('alice', 'agent:test', 'linked', 'linked'))
    result = catalog.cleanup('alice')
    assert result['removed'] == 1
    with catalog.connection() as db:
        saved = json.loads(db.execute('SELECT payload FROM fleet_entity_catalog_audit WHERE id=?', (result['audit_id'],)).fetchone()[0])
        assert saved['records'] == [{'table':'fleet_entities', 'id':'blank', 'payload':{}}]
        assert {tuple(r) for r in db.execute('SELECT owner,id FROM fleet_entities')} == {('alice','linked'),('alice','stale'),('bob','blank')}
    assert catalog.cleanup('alice')['removed'] == 0


def entry(identity, kind='send-message', message=None, **extra):
    body = dict(kind=kind, timestampMs=1795132800000, message=message or {'type':'text','content':'Completed the evidence review.'}, **extra)
    return {'entryId':identity, 'body':base64.b64encode(json.dumps(body).encode()).decode()}


def test_grok_outputs_deduplicate_and_feed_briefings(grok, fleet, bridge, monkeypatch):
    g, state = grok
    g.connect_pair(USER, state['pair'], 'test')
    agent = bots(fleet)[0]
    rows = [entry('reply'), entry('internal', kind='message', role='assistant'),
            entry('approval', message={'type':'credential-request','content':'secret'}),
            entry('stream', isStreaming=True), entry('attachment', message={'type':'attachment','file_name':'report.md','url':'https://example.test/?secret=token'})]
    monkeypatch.setattr(g, 'request', lambda *args, **kwargs: {'entries':rows})
    assert grokbot_outputs.refresh(USER, agent['id'])['recorded'] == 2
    assert grokbot_outputs.refresh(USER, agent['id'])['recorded'] == 2
    with fleet.store().connect() as db:
        outputs = [json.loads(r[0]) for r in db.execute('SELECT payload FROM fleet_objects WHERE user=?', (USER,))]
    assert len(outputs) == 2
    assert all('secret' not in json.dumps(v) for v in outputs)
    from modules.agents.briefings import agent_updates
    updates = agent_updates(USER)
    assert any(v['answer'] == 'Completed the evidence review.' for v in updates)
    assert not agent_updates('other-owner')
    with pytest.raises(Exception):
        grokbot_outputs.refresh('other-owner', agent['id'])
    monkeypatch.setattr(g, 'request', lambda *args, **kwargs: {'error':'changed'})
    with pytest.raises(Exception, match='format changed'):
        grokbot_outputs.refresh(USER, agent['id'])
    with fleet.store().connect() as db:
        assert db.execute('SELECT count(*) FROM fleet_objects WHERE user=?', (USER,)).fetchone()[0] == 2


@pytest.mark.parametrize('width', [390, 1440])
def test_entity_catalog_browser(fleet, bridge, authenticated_client, tmp_path, width):
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def route(r):
            u = urlparse(r.request.url)
            response = authenticated_client.request(r.request.method, u.path + ('?' + u.query if u.query else ''),
                content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code, content_type=response.headers.get('content-type','text/html'), body=response.content)
        page.route('https://fleet.test/**', route)
        page.goto('https://fleet.test/agents')
        drawer_close = page.get_by_role('button', name='Close Agent work drawer', exact=True)
        if width < 600 and drawer_close.is_visible():
            drawer_close.click()
        page.screenshot(path=str(tmp_path/f'entity-before-{width}.png'))
        page.get_by_role('button', name='Manage entity types', exact=True).click()
        dialog = page.get_by_role('dialog', name='Manage entity types', exact=True)
        expect(dialog.get_by_role('button', name='Edit Skill', exact=True)).to_be_visible()
        page.screenshot(path=str(tmp_path/f'entity-catalog-{width}.png'))
        dialog.get_by_role('button', name='Edit Skill', exact=True).click()
        dialog.get_by_label('Name', exact=True).fill('Expertise')
        assert dialog.get_by_label('Type key', exact=True).input_value() == 'skill'
        dialog.get_by_role('button', name='Save type', exact=True).click()
        expect(dialog.get_by_role('button', name='Edit Expertise', exact=True)).to_be_visible()
        dialog.get_by_role('button', name='Add entity type', exact=True).click()
        dialog.get_by_label('Name', exact=True).fill('Document')
        dialog.get_by_label('Description', exact=True).fill('A saved document.')
        dialog.get_by_label('Mapping keywords', exact=True).fill('document, saved')
        dialog.get_by_role('button', name='Save type', exact=True).click()
        expect(dialog.get_by_role('button', name='Edit Document', exact=True)).to_be_visible()
        dialog.get_by_label('Find entity types', exact=True).fill('document')
        expect(dialog.locator('.fleet-type-card')).to_have_count(1)
        assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth')
        dialog.get_by_role('button', name='Remove Document', exact=True).click()
        dialog.get_by_role('button', name='Confirm removal', exact=True).click()
        expect(dialog.get_by_text('No matching entity types.', exact=True)).to_be_visible()
        dialog.get_by_label('Find entity types', exact=True).fill('')
        dialog.get_by_role('button', name='Clean empty records', exact=True).click()
        expect(dialog.get_by_role('status')).to_contain_text('0 empty records removed')
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(page.get_by_role('button', name='Manage entity types', exact=True)).to_be_focused()
        assert not errors
        browser.close()
