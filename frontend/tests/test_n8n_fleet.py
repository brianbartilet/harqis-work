"""n8n sync boundaries, dependency projection and execution capture."""
import json
import pytest
from fastapi import HTTPException
from modules.integrations import n8n_fleet as fleet, n8n_demo
from modules.agents import service


@pytest.fixture
def linked(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_N8N_MOCK', '1')
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HARQIS_DATA_ROOT', str(tmp_path))
    monkeypatch.setenv('HFL_AGENT_BRIDGE_STORE_PATH', str(tmp_path/'bridge.sqlite3'))
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path/'connectors.sqlite3'))
    return fleet.link('alice', {'remote_id': 'atlas', 'profile': {**service.defaults('My local Atlas'), 'runtime': 'n8n'}})['item']


def test_import_graph_and_preserve_legacy_profile(linked):
    assert linked['name'] == 'My local Atlas'
    assert linked['n8n_snapshot']['url'] == 'https://n8n.example.test/projects/operations/agents/atlas'
    assert len(linked['n8n_snapshot']['workflows']) == 3
    assert len(linked['n8n_snapshot']['executions']) == 6
    again = fleet.link('alice', {'remote_id': 'atlas'})
    assert again['existing'] and again['item']['id'] == linked['id']
    n8n_demo.change('alice')
    fresh = fleet.refresh('alice', linked['id'])['item']
    assert fresh['name'] == 'My local Atlas'
    assert fresh['remote_name'].endswith('revised in n8n')
    nodes, edges = {}, []
    def add(aid, identity, kind, label, *args, **kw):
        nodes[identity] = kind
    fleet.extend_graph([fresh], nodes, lambda *args: edges.append(args), add)
    assert 'application' in nodes.values()
    assert any(e[2] == 'calls' for e in edges)
    assert any(e[2] == 'execution' for e in edges)


def test_link_refreshes_an_agent_imported_by_legacy_sync(linked):
    db = service.store()
    old = dict(linked)
    old.pop('n8n_snapshot')
    db.save(old, identity=old['id'], version=old['version'])
    result = fleet.link('alice', {'remote_id': 'atlas'})
    assert result['existing']
    assert result['item']['id'] == linked['id']
    assert result['item']['name'] == 'My local Atlas'
    assert len(result['item']['n8n_snapshot']['workflows']) == 3


def test_owner_and_remote_conflict(linked):
    with pytest.raises(HTTPException) as denied:
        fleet.refresh('bob', linked['id'])
    assert denied.value.status_code == 404
    snapshot = linked['n8n_snapshot']
    edit = {'version': linked['version'], 'config_hash': snapshot['config_hash'], 'name': 'Changed', 'instructions': 'Instructions'}
    n8n_demo.change('alice')
    with pytest.raises(HTTPException) as conflict:
        fleet.edit('alice', linked['id'], edit)
    assert conflict.value.status_code == 409
    fresh = fleet.refresh('alice', linked['id'])['item']
    edit.update(version=fresh['version'], config_hash=fresh['n8n_snapshot']['config_hash'])
    result = fleet.edit('alice', linked['id'], edit)['item']
    assert result['n8n_snapshot']['name'] == 'Changed'
    assert n8n_demo.MockN8n('alice').agent('atlas')['config']['instructions'] == 'Instructions'
    assert result['name'] == 'My local Atlas'


def test_capture_deduplicates_and_preview_never_delivers(linked, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Mock receipts must never reach the corpus')
    monkeypatch.setattr('workflows.hfl.persistence.submit_hfl_entry', forbidden)
    fleet.capture('alice', linked['id'])
    fleet.capture('alice', linked['id'])
    events = [e for e in service.store().events(linked['id']) if e['payload']['kind'] == 'n8n-execution']
    assert len(events) == 6
    assert all(e['payload']['mock'] and not e['delivered'] for e in events)


def test_projection_excludes_credentials_and_payloads():
    view = fleet.workflow_view({'id': 'w', 'name': 'Flow', 'nodes': [{'type': 'n8n-nodes-base.slack', 'credentials': {'token':'SECRET'}, 'parameters': {'text': 'PRIVATE'}}]}, 'https://example.test')
    assert 'SECRET' not in json.dumps(view) and 'PRIVATE' not in json.dumps(view)


def test_pagination_does_not_loop_forever():
    class Client:
        def request(self, *args, **kwargs):
            return {'data': [], 'nextCursor': 'repeat'}
    assert fleet.workflows(Client()) == ([], True)


def test_mock_requires_both_flags(monkeypatch):
    monkeypatch.setenv('HARQIS_N8N_MOCK', '1')
    monkeypatch.delenv('HFL_TIMELINE_LOCAL_PREVIEW', raising=False)
    with pytest.raises(HTTPException):
        n8n_demo.connection('alice')


def test_real_capture_delivery_uses_source_time_and_dedup(linked, monkeypatch):
    from modules.agents.audit import deliver_pending
    db = service.store()
    payload = {'kind': 'n8n-execution', 'workflow_name': 'Briefing', 'status': 'success',
               'stopped_at': '2026-11-15T01:00:12+00:00', 'url': 'https://n8n.example.test/workflow/w/executions/42'}
    db.event('n8n-execution:42', linked['id'], payload)
    db.event('unrelated-receipt', linked['id'], {'kind': 'profile', 'name': 'Unrelated'})
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '0')
    calls = []
    def submit(entry, **kwargs):
        calls.append((entry, kwargs))
        return {'delivery': 'persisted'}
    monkeypatch.setattr('workflows.hfl.persistence.submit_hfl_entry', submit)
    assert deliver_pending(['n8n-execution:42'])['delivered'] == 1
    assert deliver_pending(['n8n-execution:42'])['delivered'] == 0
    assert any(e['id'] == 'unrelated-receipt' and not e['delivered'] for e in db.events(pending=True))
    assert len(calls) == 1
    assert calls[0][0].when.day == 15
    assert calls[0][0].references == (payload['url'],)
    assert calls[0][1]['dedup_key'] == 'fleet:n8n-execution:42'


def test_sync_imports_standalone_workflows_and_refreshes_existing_profile(linked, monkeypatch):
    from modules.integrations.n8n import sync
    monkeypatch.setattr(n8n_demo, 'WORKFLOWS', [*n8n_demo.WORKFLOWS, {'id': 'standalone', 'name': 'Standalone', 'nodes': []}])
    result = sync('alice')
    assert result['imported'] >= 1
    library = service.store().get(result['library_id'])
    assert library['n8n_library'] and not library['n8n_snapshot']['can_edit']
    assert any(w['id'] == 'standalone' for w in library['n8n_snapshot']['workflows'])
    assert service.store().get(linked['id'])['name'] == 'My local Atlas'
    assert service.store().get(linked['id'])['n8n_snapshot']['workflows']
    again = sync('alice')
    assert again['library_id'] == result['library_id']
    with pytest.raises(HTTPException) as exc:
        fleet.edit('alice', result['library_id'], {})
    assert exc.value.status_code == 422


def test_rest_only_sync_still_imports_workflows(linked, monkeypatch):
    from modules.integrations.n8n import sync
    from modules.integrations.service import connected
    _, client = connected('alice', 'n8n')
    def unavailable(*args, **kwargs):
        raise HTTPException(409, 'MCP disabled')
    monkeypatch.setattr(type(client), 'agents', unavailable)
    result = sync('alice')
    assert result['imported'] == 0
    assert result['workflows'] >= 3
    assert result['warnings']


def test_browser_origin_does_not_change_api_address(linked, monkeypatch):
    original = fleet.connected
    def connected(user, provider):
        connection, client = original(user, provider)
        return {**connection, 'public_url': 'http://harqis-ones-mac-mini:5678'}, client
    monkeypatch.setattr(fleet, 'connected', connected)
    fresh = fleet.refresh('alice', linked['id'])['item']
    assert fresh['connector_site'] == 'https://n8n.example.test'
    snapshot = fresh['n8n_snapshot']
    assert snapshot['url'].startswith('http://harqis-ones-mac-mini:5678/')
    assert all(w['url'].startswith('http://harqis-ones-mac-mini:5678/workflow/') for w in snapshot['workflows'])
    assert all(r['url'].startswith('http://harqis-ones-mac-mini:5678/workflow/') for r in snapshot['executions'])


def test_archived_workflow_and_navigation_validation():
    from modules.integrations.n8n import browser_origin
    from modules.agents.ecosystem import safe_url
    view = fleet.workflow_view({'id': 'one', 'isArchived': True, 'active': False}, 'http://host:5678')
    assert view['archived'] and not view['active']
    assert safe_url(view['url'], allow_http=True) == view['url']
    assert safe_url(view['url']) == ''
    for value in ['javascript:alert(1)', 'http://user:password@host', 'http://host/path', 'http://host:bad']:
        with pytest.raises(HTTPException):
            browser_origin(value)


def test_library_projects_as_connector_with_real_agent_relationship(linked):
    from modules.integrations.n8n import sync
    from modules.agents.ecosystem import graph
    result = sync('alice')
    data = graph('alice')
    hub = next(n for n in data['nodes'] if n['id'] == 'agent:' + result['library_id'])
    assert hub['kind'] == 'connector' and hub['label'] == 'n8n'
    assert any(t['id'] == 'connector' for t in data['types'])
    assert any(n['kind'] == 'agent' and n['agent_id'] == linked['id'] for n in data['nodes'])
    assert any(e['source'] == hub['id'] and e['target'] == 'agent:' + linked['id'] and e['relation'] == 'provides' for e in data['edges'])
    assert any(e['source'] == hub['id'] and ':workflow:' in e['target'] for e in data['edges'])
