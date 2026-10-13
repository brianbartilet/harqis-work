"""Contract and real HTTP checks for the canonical frontend MCP surface."""
import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
import inspect
import json
from pathlib import Path
import re
from threading import Thread
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
import pytest
import requests

from tools.frontend_coverage import MANIFEST, check, inventory


CONTRACT = json.loads(MANIFEST.read_text(encoding='utf-8'))['endpoints']
NEW = [row for row in CONTRACT if row.get('service')]


@contextmanager
def http_server(respond):
    """Exercise requests over a real socket; optionally forward into the real ASGI app."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def dispatch(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            status, headers, content = respond(self.command, self.path, dict(self.headers), body)
            self.send_response(status)
            for key, value in headers.items():
                if key.lower() not in {'content-length', 'transfer-encoding', 'connection'}:
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = dispatch

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def service(class_path, origin, token='frontend-test-hfl-api-token'):
    from apps.hfl_corpus.config import CONFIG
    module, name = class_path.rsplit('.', 1)
    return getattr(import_module(module), name)(CONFIG, api_url=origin, api_key=token)


@pytest.fixture(scope='module')
def mcp_server():
    from apps.hfl_corpus.mcp import register_hfl_corpus_tools
    server = FastMCP('frontend-contract-test')
    register_hfl_corpus_tools(server)
    return server


@pytest.fixture(scope='module')
def mcp_tools(mcp_server):
    return {t.name: t for t in asyncio.run(mcp_server.list_tools())}


def test_every_frontend_route_has_a_reviewed_contract():
    result = check()
    assert result['ok'], result['errors']


@pytest.mark.parametrize('path,status,tools,expected', [
    ('/api/hfl/timeline/ideas/share-context', 'covered', ['raw_context'], 'Internal sharing input must remain protocol-only'),
    ('/api/hfl/timeline/ideas/share-context/attachments/{kind}/{source_id}/{attachment_id}', 'protocol', ['raw_attachment'], 'Internal sharing input must remain protocol-only'),
    ('/api/hfl/timeline/ideas/share-context/new', 'protocol', [], 'Canonical HFL endpoint needs a dedicated tool'),
])
def test_internal_sharing_exception_is_exact_and_cannot_expose_tools(tmp_path, monkeypatch, path, status, tools, expected):
    from tools import frontend_coverage
    monkeypatch.setattr(frontend_coverage, 'inventory', lambda root: {('GET', path): {}})
    (tmp_path / 'frontend').mkdir()
    (tmp_path / 'frontend/mcp_coverage.json').write_text(json.dumps({'endpoints': [
        dict(method='GET', path=path, status=status, tools=tools, reason='Regression fixture'),
    ]}), encoding='utf-8')
    assert any(expected in error for error in check(tmp_path)['errors'])


def test_reuse_routes_preserve_authenticated_canonical_proxy():
    from modules.hfl_corpus.intent_reuse import router
    from modules.hfl_corpus.timeline import TimelineRoute

    assert len(router.routes) == 9
    assert all(isinstance(route, TimelineRoute) for route in router.routes)


def test_static_inventory_matches_runtime_and_standalone_is_complete():
    from main import app as frontend
    from hfl_api import app as standalone
    def routes(app):
        # FastAPI supports both eagerly copied routes and lazy included routers.
        try:
            from fastapi.routing import iter_route_contexts
        except ImportError:
            return app.routes
        return iter_route_contexts(app.routes)

    mounted = {(method, r.path) for r in routes(frontend) if getattr(r, 'methods', None) for method in r.methods}
    assert set(inventory()) == mounted
    canonical = {(method, path) for method, path in mounted if path.startswith('/api/hfl/')}
    standalone_rows = [(method, r.path) for r in routes(standalone) if (getattr(r, 'path', '') or '').startswith('/api/hfl/') for method in r.methods]
    assert len(standalone_rows) == len(set(standalone_rows)), 'Duplicate standalone operations'
    assert set(standalone_rows) == canonical


def test_all_canonical_routes_map_to_discoverable_tools(mcp_tools):
    names = {row['tools'][0] for row in CONTRACT if row['status'] == 'covered'}
    assert names == set(mcp_tools)
    for row in NEW:
        cls, method = row['service'].rsplit('.', 1)
        module, name = cls.rsplit('.', 1)
        signature = inspect.signature(getattr(getattr(import_module(module), name), method))
        properties = mcp_tools[row['tools'][0]].inputSchema['properties']
        assert set(properties) == set(signature.parameters) - {'self'}


def test_write_classification_and_cli_schema(mcp_tools, tmp_path, monkeypatch):
    from tools.catalog import is_write_tool
    from tools.cli import run
    from agents.projects.permissions.enforcer import PermissionDenied
    read_posts = {'analyze_hfl_corpus_entity_selection', 'get_hfl_corpus_rendered_markdown'}
    for row in NEW:
        name = row['tools'][0]
        readonly = (row['method'] == 'GET' and not name.startswith('download_')) or name in read_posts
        assert mcp_tools[name].annotations.readOnlyHint is readonly
        assert mcp_tools[name].annotations.destructiveHint is not readonly
        if (row['method'] != 'GET' and name not in read_posts) or name.startswith('download_'):
            assert is_write_tool(name), name
    for name in ('create_hfl_corpus_map', 'create_hfl_corpus_entity_merge', 'update_hfl_corpus_document'):
        assert run(['schema', 'hfl_corpus', name])['input_schema'] == mcp_tools[name].inputSchema
    monkeypatch.setenv('HARQIS_CLI_AUDIT_LOG', str(tmp_path / 'audit.jsonl'))
    with pytest.raises(PermissionDenied, match='--confirm-write'):
        run(['call', 'hfl_corpus', 'delete_hfl_corpus_map', '--input', '{"identity":"blocked","version":1}'])


@pytest.fixture(scope='module')
def recording_api():
    records = []

    def respond(method, path, headers, body):
        records.append((method, path, headers, body))
        if urlsplit(path).path.endswith('/timeline/evidence'):
            return 303, {'Location': '/hfl-corpus/document/test.md#entry'}, b''
        if method == 'GET' and re.search(r'/attachments/[^/]+$', urlsplit(path).path):
            return 200, {'Content-Type': 'application/octet-stream'}, b'\x00\xffattachment\r\n'
        return 200, {'Content-Type': 'application/json'}, b'{"ok":true}'

    with http_server(respond) as origin:
        yield origin, records


@pytest.mark.parametrize('row', NEW, ids=lambda row: row['tools'][0])
def test_every_new_service_uses_reviewed_http_contract(row, recording_api, tmp_path, mcp_server, monkeypatch):
    origin, records = recording_api
    cls, method = row['service'].rsplit('.', 1)
    target = getattr(service(cls, origin), method)
    values = {}
    path_fields = re.findall(r'{([^}:]+)(?::[^}]+)?}', row['path'])
    sample_file = tmp_path / 'input.txt'
    sample_file.write_text('supporting evidence', encoding='utf-8')
    for name, parameter in inspect.signature(target).parameters.items():
        if name in path_fields:
            values[name] = 123 if name == 'decision_id' else 'id +%?#'
        elif name == 'destination':
            values[name] = str(tmp_path / 'download.bin')
        elif name == 'file_paths':
            values[name] = [str(sample_file)]
        elif parameter.default is inspect.Parameter.empty:
            annotation = str(parameter.annotation)
            values[name] = 7 if annotation == 'int' else [] if 'list' in annotation else {} if annotation == 'dict' else 'test'
    target(**values)
    direct_record = records[-1]
    import copy
    import apps.hfl_corpus.mcp as adapter
    config = copy.deepcopy(adapter.CONFIG)
    config.app_data.update(api_url=origin, api_key='frontend-test-hfl-api-token')
    monkeypatch.setattr(adapter, 'CONFIG', config)
    asyncio.run(mcp_server._tool_manager.call_tool(row['tools'][0], values))
    assert records[-1][:2] == direct_record[:2], 'MCP and service must use the same HTTP operation'
    if 'file_paths' not in values:
        assert records[-1][3] == direct_record[3], 'MCP must preserve the service request body'
    method_sent, path, headers, body = records[-1]
    assert method_sent == row['method']
    expected = row['path']
    for key in path_fields:
        expected = re.sub(r'\{' + re.escape(key) + r'(?::[^}]+)?\}', lambda _: str(values[key]), expected)
    assert unquote(urlsplit(path).path) == expected
    assert headers['Authorization'] == 'Bearer frontend-test-hfl-api-token'
    if 'file_paths' in values:
        assert 'multipart/form-data; boundary=' in headers['Content-Type']
        assert b'name="files"' in body and b'supporting evidence' in body
    if 'destination' in values:
        assert Path(values['destination']).read_bytes() == b'\x00\xffattachment\r\n'
    if method == 'create_map':
        assert json.loads(body)['name'] == 'test' and 'title' not in json.loads(body)
    if method == 'create_checklist_action':
        assert json.loads(body) == {key: values[key] for key in ('version', 'checklist_id', 'item_id', 'request_id', 'item')}
    if method == 'update_graph_view':
        assert json.loads(body)['revision'] == 7
    if method == 'delete_graph_view':
        assert parse_qs(urlsplit(path).query)['revision'] == ['7']
    if method.startswith('update_') and 'version' in values:
        assert json.loads(body)['version'] == 7


@pytest.fixture
def canonical_api(monkeypatch, tmp_path):
    from modules.hfl_corpus import corpus
    # Visibility checks need a real corpus, independent of host data or Docker logs.
    corpus_root = tmp_path / 'corpus'
    corpus_root.mkdir()
    monkeypatch.setattr(corpus, 'resolve_corpus_root', lambda: corpus_root)
    from hfl_api import app
    # No lifespan: avoids corpus prewarming against a configured live directory.
    client = TestClient(app)

    def respond(method, path, headers, body):
        response = client.request(method, path, headers={k: v for k, v in headers.items() if k.lower() != 'host'}, content=body, follow_redirects=False)
        return response.status_code, dict(response.headers), response.content

    with http_server(respond) as origin:
        yield origin
    client.close()


def test_item_connection_search_and_revision_payloads(recording_api):
    origin, records = recording_api
    api = service('apps.hfl_corpus.references.web.api.ideas.ApiServiceHflCorpusIdeas', origin)
    api.list_item_connection_options(query='plan + review', offset=50)
    assert parse_qs(urlsplit(records[-1][1]).query) == {'query': ['plan + review'], 'offset': ['50']}
    payload = {
        'operation': 'update', 'revision': 'current-revision',
        'edge': {'source': 'idea:one', 'target': 'action:two', 'relation': 'related-to'},
        'replacement': {'source': 'idea:one', 'target': 'action:two', 'relation': 'depends-on'},
    }
    api.update_item_connection(payload)
    assert records[-1][:2] == ('POST', '/api/hfl/timeline/ideas/item-connections')
    assert json.loads(records[-1][3]) == payload


def test_consolidation_decision_payloads(recording_api):
    origin, records = recording_api
    api = service('apps.hfl_corpus.references.web.api.entities.ApiServiceHflCorpusEntities', origin)
    decision = {
        'decision': 'merge', 'reason': 'Matching identity confirmed by source evidence',
        'facts': [{'left_quote': 'Acme', 'right_quote': 'Acme', 'explanation': 'Same employer'}],
        'contradictions': [], 'aliases': ['Example'], 'partial_aliases': [],
    }
    api.update_entity_consolidation_decision('run-1', 'pair-1', decision)
    assert records[-1][0:2] == ('POST', '/api/hfl/entities/consolidation/run-1/decisions/pair-1')
    assert json.loads(records[-1][3]) == decision
    api.update_entity_consolidation_decisions('run-1', {'pair-1': decision})
    assert records[-1][0:2] == ('POST', '/api/hfl/entities/consolidation/run-1/decisions')
    assert json.loads(records[-1][3]) == {'decisions': {'pair-1': decision}}


def test_map_and_goal_lifecycle_over_real_http(canonical_api):
    api = service('apps.hfl_corpus.references.web.api.ideas.ApiServiceHflCorpusIdeas', canonical_api)
    idea = api.create_idea(str(uuid4()), 'Explore a test idea')['item']
    board = api.create_map(str(uuid4()), 'Test map')['item']
    goal = api.create_goal(str(uuid4()), 'Test goal', {'body': 'Measurable outcome'})['item']
    changed = api.update_map(board['id'], board['version'], {'purpose': 'Review options'})['item']
    assert api.get_map(board['id'])['item']['purpose'] == 'Review options'
    with pytest.raises(requests.HTTPError) as conflict:
        api.update_map(board['id'], board['version'], {'name': 'Stale edit'})
    assert conflict.value.response.status_code == 409
    assert api.update_goal(goal['id'], goal['version'], {'status': 'active'})['item']['status'] == 'active'
    assert api.update_idea(idea['id'], idea['version'], {'status': 'dismissed'})['item']['status'] == 'dismissed'
    api.delete_map(board['id'], changed['version'])
    assert api.list_boards()['maps'] == []


def test_graph_view_revision_and_auth_over_real_http(canonical_api):
    cls = 'apps.hfl_corpus.references.web.api.graph_views.ApiServiceHflCorpusGraphViews'
    api = service(cls, canonical_api)
    view = api.create_graph_view('Test view', {'query': 'project'})
    updated = api.update_graph_view(view['id'], 'Revised view', {'query': 'revised'}, view['revision'])
    assert updated['revision'] == view['revision'] + 1
    with pytest.raises(requests.HTTPError) as conflict:
        api.delete_graph_view(view['id'], view['revision'])
    assert conflict.value.response.status_code == 409
    api.delete_graph_view(view['id'], updated['revision'])
    assert api.list_graph_views()['views'] == []
    with pytest.raises(requests.HTTPError) as unauthorized:
        service(cls, canonical_api, token='invalid').list_graph_views()
    assert unauthorized.value.response.status_code == 401


def test_idea_attachments_roundtrip(canonical_api, tmp_path):
    api = service('apps.hfl_corpus.references.web.api.ideas.ApiServiceHflCorpusIdeas', canonical_api)
    idea = api.create_idea(str(uuid4()), 'Attachment test')['item']
    source = tmp_path / 'evidence.bin'
    source.write_bytes(b'\x00\xffproof\r\n')
    result = api.upload_idea_attachments(idea['id'], [str(source)])
    attachment = result['attachments'][0]
    assert api.list_idea_attachments(idea['id'])['attachments'][0]['id'] == attachment['id']
    destination = tmp_path / 'download.bin'
    api.download_idea_attachment(idea['id'], attachment['id'], str(destination))
    assert destination.read_bytes() == source.read_bytes()
    api.delete_idea_attachment(idea['id'], attachment['id'])
    assert api.list_idea_attachments(idea['id'])['attachments'] == []


def test_query_encoding_and_concurrency_payload(recording_api):
    origin, records = recording_api
    api = service('apps.hfl_corpus.references.web.api.timeline.ApiServiceHflCorpusTimeline', origin)
    api.list_timeline_items(include_closed=True, scope={'any': [{'q': '#project'}]})
    query = parse_qs(urlsplit(records[-1][1]).query)
    assert query['include_closed'] == ['true']
    assert json.loads(query['scope'][0]) == {'any': [{'q': '#project'}]}
    api.update_timeline_item('item', 7, {'version': 99, 'notes': 'reviewed'})
    assert json.loads(records[-1][3]) == {'version': 7, 'notes': 'reviewed'}
    with pytest.raises(ValueError, match='attribution'):
        api.update_timeline_item('item', 7, {'_agent_actor': 'forged'})
    entities = service('apps.hfl_corpus.references.web.api.entities.ApiServiceHflCorpusEntities', origin)
    entities.list_entities(sources=['one', 'two'])
    assert parse_qs(urlsplit(records[-1][1]).query)['sources'] == ['one', 'two']


def test_existing_document_tools_forward_new_parameters(recording_api):
    origin, records = recording_api
    api = service('apps.hfl_corpus.references.web.api.documents.ApiServiceHflCorpusDocuments', origin)
    api.list_documents(include_entries=True, activity_year=2026, activity_from_year=2025, scope={'any': [{'q': 'test'}]})
    query = parse_qs(urlsplit(records[-1][1]).query)
    assert query['include_entries'] == ['true']
    assert query['activity_year'] == ['2026']
    assert query['activity_from_year'] == ['2025']
    assert json.loads(query['scope'][0]) == {'any': [{'q': 'test'}]}
    api.list_matches('test.md', scope={'any': [{'q': 'another'}]})
    assert json.loads(parse_qs(urlsplit(records[-1][1]).query)['scope'][0]) == {'any': [{'q': 'another'}]}
    api.update_document('test.md', 'replacement', expected_updated_at='2026-09-23T10:00:00')
    assert json.loads(records[-1][3])['expected_updated_at'] == '2026-09-23T10:00:00'


def test_mcp_execution_reaches_canonical_service(canonical_api, monkeypatch):
    import copy
    import apps.hfl_corpus.mcp as adapter
    config = copy.deepcopy(adapter.CONFIG)
    config.app_data.update(api_url=canonical_api, api_key='frontend-test-hfl-api-token')
    monkeypatch.setattr(adapter, 'CONFIG', config)
    server = FastMCP('frontend-execution-test')
    adapter.register_hfl_corpus_tools(server)
    created = asyncio.run(server._tool_manager.call_tool('create_hfl_corpus_map', {'request_id': str(uuid4()), 'name': 'Created through MCP'}))
    result = asyncio.run(server._tool_manager.call_tool('get_hfl_corpus_map', {'identity': created['item']['id']}))
    assert result['item']['name'] == 'Created through MCP'


@pytest.mark.parametrize('identity', ['', '.', '..', '../escape', 'a/b', 'a\\b', 'x\r\nInjected'])
def test_resource_ids_cannot_change_routes(identity, recording_api):
    origin, records = recording_api
    before = len(records)
    api = service('apps.hfl_corpus.references.web.api.ideas.ApiServiceHflCorpusIdeas', origin)
    with pytest.raises(ValueError, match='resource ID'):
        api.get_map(identity)
    assert len(records) == before


def test_redirect_does_not_forward_auth_or_replace_file(tmp_path):
    requests_seen = []

    def respond(method, path, headers, body):
        requests_seen.append(path)
        return 302, {'Location': '/unexpected'}, b''

    with http_server(respond) as origin:
        api = service('apps.hfl_corpus.references.web.api.ideas.ApiServiceHflCorpusIdeas', origin)
        with pytest.raises(ValueError, match='redirect'):
            api.list_boards()
        target = tmp_path / 'existing.bin'
        target.write_bytes(b'keep')
        with pytest.raises(ValueError, match='redirect'):
            api.download_idea_attachment('idea', 'attachment', str(target))
        assert target.read_bytes() == b'keep'
    assert '/unexpected' not in requests_seen


@pytest.mark.parametrize('method,kwargs,query,body', [
    ('create_entity_backfill', {'include_new_types': True}, {'include_new_types': ['true']}, None),
    ('get_entity_matching', {'all': True}, {'all': ['true']}, None),
    ('create_entity_merge_batch', {'groups': [{'entity_ids': ['a','b'], 'name': 'Reviewed',
        'request_id': '12345678-1234-5678-1234-567812345678', 'preview_token': 'signed-preview',
        'profile': {'notes': 'Keep reviewed notes'}}]}, {}, 'groups'),
])
def test_entity_review_options_preserve_wire_contract(recording_api, method, kwargs, query, body):
    origin, records = recording_api
    client = service('apps.hfl_corpus.references.web.api.entities.ApiServiceHflCorpusEntities', origin)
    getattr(client, method)(**kwargs)
    _, path, _, raw = records[-1]
    assert parse_qs(urlsplit(path).query) == query
    if body:
        assert json.loads(raw) == kwargs
