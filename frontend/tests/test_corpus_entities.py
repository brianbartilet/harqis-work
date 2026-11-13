"""Evidence, lifecycle, identity, filtering, and owner-boundary regression tests."""
import pytest
from fastapi.testclient import TestClient
from modules.hfl_corpus import entities
from workflows.hfl.entity_store import get_store, VERSION


def entry(identity='one', text='Alex uses React at https://example.test/project', source='notes', date='2026-09-01'):
    return dict(id=identity, text=text, title='Project update', source=source, date=date,
                tags=['surface-hermes'], path='day.md', anchor=identity, ref='https://example.test/corpus', entities={})


@pytest.fixture
def corpus(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path/'entities.sqlite3'))
    rows = [entry()]
    monkeypatch.setattr(entities, 'current_entries', lambda: list(rows))
    return rows


def test_graph_evidence_and_filters(corpus):
    corpus.append(entry('two', source='meetings', date='2026-08-01'))
    graph = entities.graph(source='notes', since='2026-09-01')
    assert graph['entries'] == 1
    assert {n['kind'] for n in graph['nodes']} == {'entries', 'sources', 'daily'}
    assert all(e['evidence'] and e['method'] for e in graph['edges'])
    assert not any(n['label'] == 'surface-hermes' for n in graph['nodes'])
    ids = {n['id'] for n in graph['nodes']}
    assert all(e['source'] in ids and e['target'] in ids for e in graph['edges'])


def test_stale_removed_and_protected_entries_cannot_leak(corpus):
    store = get_store()
    mention = entities.mention(corpus[0], 'tools', 'React', 'uses React', 'model-extracted')
    store.save('one', entities.entry_hash(corpus[0]), [mention])
    assert any(n['label'] == 'React' for n in entities.graph()['nodes'])
    corpus[0]['text'] = 'Changed content'
    assert not any(n['label'] == 'React' for n in entities.graph()['nodes'])
    corpus.clear()  # Source adapter excludes protected and deleted entries.
    assert entities.graph()['nodes'] == []
    assert entities.enrich(use_model=False)['removed'] == 1


def test_source_failure_never_prunes(corpus, monkeypatch):
    store = get_store();store.save('one', 'digest', [])
    monkeypatch.setattr(entities, 'current_entries', lambda: (_ for _ in ()).throw(ConnectionError()))
    with pytest.raises(ConnectionError):
        entities.enrich(use_model=False)
    assert 'one' in store.records()


def test_ambiguous_people_separate_explicit_ids_join(corpus):
    a, b = entry('one'), entry('two')
    assert entities.mention(a, 'people', 'Alex', 'Alex', 'model')['id'] != entities.mention(b, 'people', 'Alex', 'Alex', 'model')['id']
    assert entities.explicit_mentions(entry('one', text='org/repo#123'))[0]['id'] == entities.explicit_mentions(entry('two', text='org/repo#123'))[0]['id']


def test_reversible_merge_and_cycle_prevention(corpus):
    store=get_store();identity=store.merge('a','b','Verified external identity')
    assert store.resolve('a') == 'b'
    with pytest.raises(ValueError): store.merge('b','a','Invalid cycle')
    store.undo(identity)
    assert store.resolve('a') == 'a'


def test_explicit_pass_does_not_skip_model_enrichment(corpus, monkeypatch):
    assert entities.enrich(use_model=False)['processed'] == 1
    assert entities.enrich(use_model=False)['processed'] == 0
    monkeypatch.setattr(entities, 'extract_batch', lambda batch: {e['id']: [] for e in batch})
    assert entities.enrich(use_model=True)['processed'] == 1
    assert get_store().records()['one']['version'] == VERSION


def test_changes_during_model_call_are_discarded(corpus, monkeypatch):
    def extract(batch):
        corpus.clear()
        return {'one': []}
    monkeypatch.setattr(entities, 'extract_batch', extract)
    assert entities.enrich()['processed'] == 0
    assert get_store().records() == {}


def test_authenticated_routes_and_removed_duplicate_api(corpus, authenticated_client):
    from main import app
    with TestClient(app) as client:
        assert client.get('/api/hfl/entities/graph').status_code == 401
        assert client.post('/api/hfl/entities/backfill').status_code == 401
    assert authenticated_client.get('/hfl-corpus/graph').status_code == 200
    assert authenticated_client.get('/hfl-corpus/entities').status_code == 200
    assert authenticated_client.get('/api/hfl/entities/graph').json()['entries'] == 1
    assert authenticated_client.post('/api/knowledge/capture').status_code == 404
    assert authenticated_client.post('/api/knowledge/ask').status_code == 404


def test_broker_failure_retains_enrichment_intent(corpus, monkeypatch):
    from workflows.hfl.entity_events import request_enrichment
    from core.apps.sprout.app.celery import SPROUT
    monkeypatch.setattr(SPROUT, 'send_task', lambda *a, **kw: (_ for _ in ()).throw(ConnectionError()))
    assert request_enrichment('one')['state'] == 'pending'
    with get_store().connection() as db:
        assert db.execute('SELECT id FROM pending').fetchone()[0] == 'one'


def test_remote_manifest_reads_entries_without_document_fanout(monkeypatch):
    from types import SimpleNamespace
    from modules.hfl_corpus.remote import RemoteCorpusClient
    client = RemoteCorpusClient('https://example.test', 'fake-token')
    payload = {'total_results': 1, 'results': [{'relative_path': 'day.md', 'name': 'day',
        'created_at': '2026-09-01', 'updated_at': '2026-09-01', 'entries': []}]}
    monkeypatch.setattr(client, '_get', lambda *a, **kw: SimpleNamespace(json=lambda: payload))
    monkeypatch.setattr(client, 'document', lambda *a, **kw: pytest.fail('Unexpected per-document fetch'))
    documents, scope = client.knowledge_documents('all')
    assert scope == 'all' and len(documents) == 1


def test_source_adapter_excludes_protected_entries(corpus, monkeypatch):
    from types import SimpleNamespace
    from modules.hfl_corpus import entity_source
    from modules.hfl_corpus.corpus import CorpusEntry
    from modules.hfl_corpus.remote import RemoteCorpusClient
    def make(name, secret=False):
        return CorpusEntry(anchor=name, header='2026-09-01', moment=name, what_happened=name,
                           tags=(), text=name, secret=secret)
    document=SimpleNamespace(relative_path='day.md', entries=(make('allowed'),make('hidden',True)))
    monkeypatch.setattr(entity_source, 'get_settings', lambda: SimpleNamespace(hfl_corpus_api_url='https://example.test',hfl_corpus_api_token='fake-token'))
    monkeypatch.setattr(RemoteCorpusClient, 'knowledge_documents', lambda *a, **kw: ((document,), 'all'))
    rows,_=entity_source.collect_entries(get_store(),'all')
    assert [e['title'] for e in rows] == ['allowed']


def test_urls_excluded_from_old_cache_and_new_extraction(corpus):
    store = get_store()
    for label in ['https://example.test/path', 'www.example.com', 'example.com/path', 'mailto:alex@example.com']:
        assert entities.is_link(label)
    assert entities.explicit_mentions(corpus[0]) == []
    old = entities.mention(corpus[0], 'objects', 'https://example.test/project', 'link', 'reference', 'https://example.test/project')
    store.save('one', entities.entry_hash(corpus[0]), [old])
    assert entities.entity_index() == []
    assert not any(n['kind'] == 'objects' for n in entities.graph()['nodes'])


def test_profile_survives_rebuild_and_source_removal(corpus, authenticated_client):
    store = get_store()
    m = entities.mention(corpus[0], 'people', 'Alex', 'Alex', 'model-extracted')
    store.save('one', entities.entry_hash(corpus[0]), [m])
    payload = dict(name='Alex Tan', categories=['Friends', 'Friends'], emails=['alex@example.com'], phones=['+65 8123 4567'], notes='Met at a workshop',
                   references=['https://example.com/alex', 'C:\\Notes\\Alex.md', 'file:///notes/alex.pdf'])
    response = authenticated_client.post('/api/hfl/entities/profile/' + m['id'], json=payload)
    assert response.status_code == 200
    assert response.json()['profile']['categories'] == ['Friends']
    assert any(n['label'] == 'Alex Tan' for n in entities.graph()['nodes'])
    corpus.clear()
    entities.enrich(use_model=False)
    entity = entities.entity_index()[0]
    assert entity['entries'] == [] and entity['profile']['notes'] == payload['notes']
    assert entity['profile']['emails'] == payload['emails']
    assert entity['profile']['references'] == payload['references']
    assert entities.entity_index(source='notes') == []


def test_profile_validation_and_owner_boundary(corpus, authenticated_client):
    from main import app
    with TestClient(app) as client:
        assert client.post('/api/hfl/entities/profile/entity:missing', json={'name': 'Alex'}).status_code == 401
    assert authenticated_client.post('/api/hfl/entities/profile/entity:missing', json={'name': 'Alex'}).status_code == 404
    for payload in [{'name': 'https://example.com'}, {'name': 'Alex', 'emails': ['invalid']}, {'name': 'Alex', 'phones': ['abc']}]:
        assert authenticated_client.post('/api/hfl/entities/profile/entity:missing', json=payload).status_code == 400


@pytest.mark.parametrize('kind', ['people', 'companies', 'tools', 'pets', 'objects'])
def test_profile_references_for_every_type(corpus, authenticated_client, monkeypatch, kind):
    monkeypatch.setattr(entities, 'entity_index', lambda: [dict(id='reference-test', kind=kind)])
    url = '/api/hfl/entities/profile/reference-test'
    references = ['https://example.com', 'https://social.example/@alex', '/notes/readme.md',
                  'file:///C:/notes/test.pdf', 'C:\\notes\\test.pdf', '\\\\server\\share\\test.pdf']
    response = authenticated_client.post(url, json={'name': 'Example', 'references': references + [' https://example.com ']})
    assert response.status_code == 200
    assert response.json()['profile']['references'] == references
    for value in ['javascript:alert(1)', 'data:text/html,test', 'https://', 'https://[broken', 'https://example.com/\nunsafe', 'x' * 2049]:
        assert authenticated_client.post(url, json={'name': 'Example', 'references': [value]}).status_code == 400


def test_directory_returns_all_entities_by_default(authenticated_client, monkeypatch):
    rows = [dict(id=str(i), label=f'Entity {i:04}', kind='tools') for i in range(1203)]
    monkeypatch.setattr(entities, 'entity_index', lambda *args: rows.copy())
    data = authenticated_client.get('/api/hfl/entities').json()
    assert data['total'] == len(data['entities']) == 1203
    limited = authenticated_client.get('/api/hfl/entities?limit=100').json()
    assert limited['total'] == 1203 and len(limited['entities']) == 100


def test_merges_preserve_profiles_for_undo(corpus):
    store = get_store()
    for identity, name in [('a', 'Alex'), ('b', 'Alex Tan')]:
        store.save_profile(identity, 'people', dict(name=name, categories=[], emails=[], phones=[], notes=name))
    decision = store.merge('a', 'b', 'Verified identity')
    assert [e['id'] for e in entities.entity_index()] == ['b']
    assert len(store.profiles()) == 2
    store.undo(decision)
    assert {e['id'] for e in entities.entity_index()} == {'a', 'b'}


def test_graph_server_budget_and_search(corpus):
    corpus[:] = [entry(str(i), text='org/repo#' + str(i), date='2026-09-01') for i in range(500)]
    corpus[-1]['title'] = 'Unique older project'
    result = entities.graph(limit=30)
    assert len(result['nodes']) <= 30 and len(result['edges']) <= 120
    assert result['truncated'] and result['matching_entries'] == 500
    ids = {n['id'] for n in result['nodes']}
    assert all(e['source'] in ids and e['target'] in ids for e in result['edges'])
    found = entities.graph(limit=30, query='Unique older project')
    assert found['matching_entries'] == 1
    assert any(n['label'] == 'Unique older project' for n in found['nodes'])
    shared = entities.graph(limit=30, shared=True)
    assert not any(n['kind'] == 'objects' for n in shared['nodes'])


def test_graph_limit_validation(corpus, authenticated_client):
    assert authenticated_client.get('/api/hfl/entities/graph?limit=1001').status_code == 422
    response = authenticated_client.get('/api/hfl/entities/graph?limit=2&query=Project')
    assert response.status_code == 200
    assert len(response.json()['nodes']) <= 2


def test_graph_multiple_sources(corpus, authenticated_client):
    corpus.extend([entry('two', source='meetings'), entry('three', source='email')])
    result = authenticated_client.get('/api/hfl/entities/graph?sources=notes&sources=email').json()
    assert result['entries'] == 2
    assert set(result['sources']) == {'notes', 'meetings', 'email'}
    assert {n['source'] for n in result['nodes'] if n['kind'] == 'entries'} == {'notes', 'email'}


def test_graph_accepts_dense_thousand(corpus, authenticated_client):
    response = authenticated_client.get('/api/hfl/entities/graph?limit=1000')
    assert response.status_code == 200
    assert response.json()['limit'] == 1000
    assert authenticated_client.get('/api/hfl/entities/graph').json()['limit'] == 100


def test_all_graph_and_sparse_budget_with_old_sources(corpus, authenticated_client):
    corpus[:] = [entry(str(i), source='notes') for i in range(1200)]
    corpus.append(entry('old', source='archive', date='2001-01-01'))
    limited = entities.graph(limit=100)
    assert len(limited['nodes']) == 100
    assert {n['label'] for n in limited['nodes'] if n['kind'] == 'sources'} == {'notes', 'archive'}
    assert limited['omitted_sources'] == 0
    complete = authenticated_client.get('/api/hfl/entities/graph?limit=0').json()
    assert len(complete['nodes']) == complete['total_nodes'] == 1205
    assert len(complete['edges']) == 2402
    assert not complete['truncated']
    filtered = entities.graph(source='archive', limit=0)
    assert filtered['matching_entries'] == 1
    assert len(filtered['nodes']) == 3


def test_source_coverage_reports_overflow(corpus):
    corpus[:] = [entry(str(i), source='source'+str(i)) for i in range(20)]
    result = entities.graph(limit=10)
    assert len(result['nodes']) == 10
    assert result['omitted_sources'] == 15


def test_saved_graph_views_persistence_conflicts_and_access(authenticated_client):
    from modules.hfl_corpus import graph_views
    from main import app
    with graph_views.connection() as db:
        db.execute('DELETE FROM graph_views')
        db.execute('DELETE FROM graph_view_last')
    url = '/api/hfl/graph-views'
    payload = {'name': 'All recent', 'state': {'density': '0', 'rolling': 30,
        'enabled': ['entries', 'sources'], 'layout': {'positions': {'entry:one': {'x': 2, 'y': 3, 'pinned': True}},
        'center': {'x': 5, 'y': 6}, 'zoom': 2}}}
    with TestClient(app) as anonymous:
        assert anonymous.get(url).status_code == 401
        assert anonymous.post(url, json=payload).status_code == 401
    first = authenticated_client.post(url, json=payload)
    assert first.status_code == 200
    first = first.json()
    identity = first['id']
    listing = authenticated_client.get(url).json()
    assert listing['last_used'] == identity
    assert listing['views'][0]['state']['layout']['positions']['entry:one']['pinned']
    updated = authenticated_client.put(url+'/'+identity, json={**payload, 'name': 'Renamed', 'revision': 1}).json()
    assert updated['revision'] == 2
    assert authenticated_client.put(url+'/'+identity, json={**payload, 'revision': 1}).status_code == 409
    assert authenticated_client.delete(url+'/'+identity+'?revision=1').status_code == 409
    assert authenticated_client.post(url+'/'+identity+'/select').status_code == 200
    assert authenticated_client.delete(url+'/'+identity+'?revision=2').status_code == 200
    assert authenticated_client.get(url).json() == {'views': [], 'last_used': None}
    assert authenticated_client.post(url+'/'+identity+'/select').status_code == 404
    assert authenticated_client.post(url, json={**payload, 'state': {'density': '99999'}}).status_code == 422


def test_entry_dialog_sanitization_and_access(corpus, authenticated_client, monkeypatch):
    monkeypatch.setattr("modules.hfl_corpus.entities_api._entry_references", lambda item: [])
    from main import app
    corpus[0]['text'] = '**Bold** <script>alert(1)</script> [bad](javascript:alert(1))'
    with TestClient(app) as client:
        assert client.get('/api/hfl/entities/entry/one').status_code == 401
    response = authenticated_client.get('/api/hfl/entities/entry/one')
    assert response.status_code == 200
    assert '<strong>Bold</strong>' in response.json()['html']
    assert '<script' not in response.json()['html'] and 'href="javascript:' not in response.json()['html']
    corpus.clear()
    assert authenticated_client.get('/api/hfl/entities/entry/one').status_code == 404


def test_entry_dialog_document_fields(corpus, authenticated_client, monkeypatch):
    from services.safe_paths import ReferenceLink
    monkeypatch.setattr('modules.hfl_corpus.entities_api._entry_references', lambda item: [
        ReferenceLink(source='https://example.test/story', label='Story reference',
                      kind='external', href='https://example.test/story')])
    corpus[0]['text'] = '2026-09-01 10:00:00\nSource: notes\nMachine: desktop\nEntry ID: one\nMoment: A moment\nWhat happened: A story\nWhy it stayed: A reason\nTags: #work\nReferences:\n- https://example.test/story'
    response = authenticated_client.get('/api/hfl/entities/entry/one')
    assert response.status_code == 200
    html = response.json()['html']
    assert '<strong>Machine:</strong>' in html
    assert '<strong>What happened:</strong>' in html
    assert 'corpus-tag-pill' in html
    assert 'href="https://example.test/story"' in html


def test_entry_locator_reads_only_current_document(corpus, authenticated_client, monkeypatch):
    from types import SimpleNamespace
    from modules.hfl_corpus.entity_source import entry_locator
    from modules.hfl_corpus import entities_api
    token = entry_locator(corpus[0])
    item = SimpleNamespace(anchor='one', header='2026-09-01 10:00', moment='A moment',
        text='2026-09-01 10:00\nEntry ID: one\nWhat happened: Current story', source='notes', tags=(), secret=False)
    document = SimpleNamespace(entries=[item])
    calls=[]
    monkeypatch.setattr(entities_api, '_entry_document', lambda path: (calls.append(path) or document, []))
    monkeypatch.setattr(entities, 'current_entries', lambda: (_ for _ in ()).throw(AssertionError('Full corpus read')))
    response = authenticated_client.get('/api/hfl/entities/entry/one', params={'locator':token})
    assert response.status_code == 200
    assert calls == ['day.md']
    assert '<h2' in response.json()['html']
    assert 'Current story' in response.json()['html']
    assert authenticated_client.get('/api/hfl/entities/entry/two', params={'locator':token}).status_code == 400
    assert authenticated_client.get('/api/hfl/entities/entry/one', params={'locator':token+'x'}).status_code == 400
    item.secret=True
    assert authenticated_client.get('/api/hfl/entities/entry/one', params={'locator':token}).status_code == 404
    item.secret=False
    document.entries=[]
    assert authenticated_client.get('/api/hfl/entities/entry/one', params={'locator':token}).status_code == 404


@pytest.mark.parametrize('use_locator', [False, True])
def test_entry_action_links_to_original_evidence(corpus, authenticated_client, monkeypatch, use_locator):
    from types import SimpleNamespace
    from urllib.parse import urlparse, parse_qs
    from modules.hfl_corpus import entities_api
    from modules.hfl_corpus.entity_source import entry_locator
    row = corpus[0]
    row.update(id='hfl-action-test', path='2026/entry & notes.md',
               text='2026-09-01 10:00\nEntry ID: hfl-action-test\nWhat happened: Follow up')
    item = SimpleNamespace(anchor=row['anchor'], header='2026-09-01 10:00',
                           moment=row['title'], text=row['text'], source='notes', tags=(), secret=False)
    monkeypatch.setattr(entities_api, '_entry_document', lambda path: (SimpleNamespace(entries=[item]), []))
    monkeypatch.setattr(entities_api, '_entry_references', lambda item: [])
    params = {'locator': entry_locator(row)} if use_locator else {}
    response = authenticated_client.get('/api/hfl/entities/entry/hfl-action-test', params=params)
    assert response.status_code == 200
    url = urlparse(response.json()['action_url'])
    assert url.path == '/hfl-corpus'
    assert parse_qs(url.query) == {'source_path': [row['path']], 'source_entry': [row['id']]}
    row['text'] = item.text = '2026-09-01 10:00\nWhat happened: Legacy entry'
    legacy_url = authenticated_client.get('/api/hfl/entities/entry/hfl-action-test', params=params).json()['action_url']
    legacy_id = parse_qs(urlparse(legacy_url).query)['source_entry'][0]
    from modules.hfl_corpus.timeline import entry_evidence_id
    assert legacy_id == entry_evidence_id(item.text)
    assert legacy_id.startswith('hfl-legacy-evidence-')


def test_enrichment_propagates_batches_entities_sources_and_dates(corpus, monkeypatch):
    from types import SimpleNamespace
    from workflows.hfl.entity_events import request_enrichment, dispatch_pending
    from workflows.knowledge.tasks.connected_hfl import refresh_corpus_entities as task
    from core.apps.sprout.app.celery import SPROUT
    corpus[:] = [entry(str(i), text='Uses React', source='notes', date='2026-09-01') for i in range(9)]
    monkeypatch.setenv('HARQIS_ENTITIES_QUEUE', 'test-entities')
    monkeypatch.setattr(SPROUT, 'send_task', lambda *a, **kw: (_ for _ in ()).throw(ConnectionError()))
    assert request_enrichment()['state'] == 'pending'
    sent=[]
    monkeypatch.setattr(SPROUT, 'send_task', lambda *a, **kw: sent.append(kw) or SimpleNamespace(id='queued'))
    assert dispatch_pending()['state'] == 'queued'
    assert sent[0]['queue'] == 'test-entities'
    batches=[]
    def extract(rows):
        batches.append(len(rows))
        return {e['id']: [entities.mention(e, 'tools', e['text'].split()[-1], e['text'], 'model-extracted')] for e in rows}
    monkeypatch.setattr(entities, 'extract_batch', extract)
    children=[]
    monkeypatch.setattr(task, 'apply_async', lambda **kw: children.append(kw) or SimpleNamespace(id='child'))
    assert task.run(**sent[0]['kwargs'])['processed'] == 8
    assert children[0]['queue'] == 'test-entities'
    assert task.run(**children[0]['kwargs'])['pending'] == 0
    assert batches == [8, 1]
    assert get_store().state('job')['state'] == 'complete'
    with get_store().connection() as db:
        assert db.execute('SELECT COUNT(*) FROM pending').fetchone()[0] == 0
    graph = entities.graph(limit=100)
    assert {n['kind'] for n in graph['nodes']} == {'entries','tools','sources','daily'}
    assert {e['relation'] for e in graph['edges']} == {'mentions','from-source','occurred-on'}
    corpus[0].update(text='Uses Python', source='meetings', date='2026-09-02')
    request_enrichment('0')
    task.run(**sent[-1]['kwargs'])
    updated = entities.graph(source='meetings', since='2026-09-02')
    assert {n['label'] for n in updated['nodes']} == {'Project update','Python','meetings','2026-09-02'}
    assert len(updated['edges']) == 3


@pytest.mark.parametrize('source', ['entities-audit', 'entity-consolidation', 'sharing-audit'])
def test_audit_sources_skip_model_fallback_and_legacy_mentions(corpus, monkeypatch, source):
    audit = entry('audit', text='org/repo#123', source=source)
    corpus[:] = [audit]
    monkeypatch.setattr(entities, 'extract_batch', lambda _: pytest.fail('audit must never reach the model'))
    assert entities.enrich()['processed'] == 0
    assert entities.explicit_mentions(audit) == []
    store = get_store()
    store.save('audit', entities.entry_hash(audit),
               [entities.mention(audit, 'people', 'Alex', 'Alex', 'model')])
    assert entities.projection()[0]['mentions'] == []
    assert entities.graph()['entries'] == 1  # Audit remains visible as an activity.
    store.save_profile('owner-linked', 'people', {'name': 'Owner linked'})
    with store.connection() as db:
        db.execute('INSERT INTO entity_activity_links(entity_id,entry_id,actor,created) VALUES (?,?,?,?)',
                   ('owner-linked', 'audit', 'owner', '2026-10-28'))
    assert [(m['id'], m['method']) for m in entities.projection()[0]['mentions']] == [
        ('owner-linked', 'user-confirmed')]
