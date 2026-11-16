import pytest
from fastapi import HTTPException
from modules.agents import entities, service
from modules.integrations import nod, nod_demo, nod_entities


@pytest.fixture
def inventory(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_NOD_MOCK', '1')
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path/'connectors.sqlite3'))
    original = nod_demo.MockNod.request
    payload = {'/api/apps': [
        {'slug': 'googlecalendar', 'name': 'Google Calendar', 'connectionId': 'personal', 'accountName': 'Personal', 'status': 'connected'},
        {'slug': 'googlecalendar', 'name': 'Google Calendar', 'connectionId': 'work', 'accountName': 'Work', 'status': 'connected'},
        {'slug': 'photos', 'name': 'Photos', 'status': 'disconnected'}],
        '/api/schedules': [{'id': 'morning', 'title': 'Morning briefing', 'enabled': True, 'cron': '0 9 * * *', 'timeZone': 'Asia/Singapore', 'watch': ['personal']}]}
    def request(self, method, path, **kwargs):
        if path in payload:
            if isinstance(payload[path], Exception):
                raise payload[path]
            assert method == 'GET'
            return payload[path]
        return original(self, method, path, **kwargs)
    monkeypatch.setattr(nod_demo.MockNod, 'request', request)
    return nod.link('alice', {})['item'], payload


def test_discovery_reuses_app_but_separates_accounts(inventory):
    agent, payload = inventory
    nod_entities.refresh('alice', agent['id'])
    data = entities.snapshot('alice')
    assert len(data['items']) == 5
    assert len([v for v in data['items'] if v['kind'] == 'application']) == 1
    assert len([v for v in data['items'] if v['kind'] == 'account']) == 2
    assert any(e['relation'] == 'watches' for e in data['edges'])
    assert entities.snapshot('bob')['items'] == []
    with pytest.raises(HTTPException):
        nod_entities.refresh('bob', agent['id'])
    # Repeated linking preserves customizations.
    service.store().save({**agent, 'name': 'My Nod'}, identity=agent['id'], version=agent['version'])
    assert nod.link('alice', {})['item']['name'] == 'My Nod'


def test_failed_partial_and_empty_discovery_preserve_observations(inventory):
    agent, payload = inventory
    payload['/api/apps'] = HTTPException(502, 'offline')
    result = nod_entities.refresh('alice', agent['id'])
    assert result['warnings']
    assert len(entities.snapshot('alice')['items']) == 5
    assert {v['state'] for v in entities.snapshot('alice')['items'] if v['kind'] == 'account'} == {'stale'}
    payload['/api/apps'] = []
    nod_entities.refresh('alice', agent['id'])
    assert {v['state'] for v in entities.snapshot('alice')['items'] if v['kind'] == 'account'} == {'no longer observed'}
    payload['/api/schedules'] = HTTPException(404, 'unsupported')
    assert 'unsupported' in nod_entities.refresh('alice', agent['id'])['warnings'][0]


def test_shared_associations_merge_refresh_and_unmerge(inventory):
    agent, _ = inventory
    app = next(v for v in entities.snapshot('alice')['items'] if v['kind'] == 'application')
    other = service.initialize().save(service.defaults('Another agent'))
    entities.associate('alice', other['id'], app['id'], True)
    duplicate = entities.entity('application', 'other-provider', 'calendar', 'Google Calendar', source='other', mock=True)
    entities.observe('alice', [duplicate], [('agent:'+other['id'], duplicate['id'], 'linked')])
    preview = entities.merge('alice', app['id'], duplicate['id'])
    assert preview['source']['id'] == app['id']
    assert not entities.snapshot('alice')['merges']
    merged = entities.merge('alice', app['id'], duplicate['id'], True)
    nod_entities.refresh('alice', agent['id'])
    data = entities.snapshot('alice')
    assert app['id'] not in {v['id'] for v in data['items']}
    assert len(next(v for v in data['items'] if v['id'] == duplicate['id'])['provenance']) == 2
    assert any(e['source'] == 'agent:'+other['id'] and e['target'] == duplicate['id'] for e in data['edges'])
    entities.associate('alice', other['id'], duplicate['id'], False)
    assert not any(e['source'] == 'agent:'+other['id'] and e['relation'] == 'linked' for e in entities.snapshot('alice')['edges'])
    with pytest.raises(HTTPException):
        entities.unmerge('bob', merged['merge_id'])
    entities.unmerge('alice', merged['merge_id'])
    assert app['id'] in {v['id'] for v in entities.snapshot('alice')['items']}
    account = next(v for v in data['items'] if v['kind'] == 'account')
    with pytest.raises(ValueError):
        entities.merge('alice', account['id'], duplicate['id'], True)


def test_graph_multiple_agents_and_scoped_accounts(inventory):
    agent, _ = inventory
    app = next(v for v in entities.snapshot('alice')['items'] if v['kind'] == 'application')
    other = service.initialize().save(service.defaults('Second agent'))
    entities.associate('alice', other['id'], app['id'], True)
    nodes, edges = {}, []
    def add(aid, identity, kind, label, *args, **kwargs):
        nodes.setdefault(identity, {'kind': kind, 'agents': []})['agents'].append(aid)
    entities.extend_graph('alice', [agent, other], nodes, lambda *edge: edges.append(edge), add)
    assert set(nodes[app['id']]['agents']) == {agent['id'], other['id']}
    accounts = [v for v in entities.snapshot('alice')['items'] if v['kind'] == 'account']
    assert all(nodes[v['id']]['agents'] == [agent['id']] for v in accounts)
    assert any(e[2] == 'owns schedule' for e in edges)
    foreign = entities.entity('account', 'another-installation', 'personal', 'Personal')
    entities.observe('alice', [foreign], [])
    with pytest.raises(ValueError):
        entities.merge('alice', accounts[0]['id'], foreign['id'], True)


def test_watch_changes_and_mock_isolation(inventory, monkeypatch):
    agent, payload = inventory
    payload['/api/schedules'][0]['watch'] = []
    nod_entities.refresh('alice', agent['id'])
    assert not any(e['relation'] == 'watches' for e in entities.snapshot('alice')['edges'])
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '0')
    assert entities.snapshot('alice')['items'] == []
