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
    payload = dict(name='Alex Tan', categories=['Friends', 'Friends'], emails=['alex@example.com'], phones=['+65 8123 4567'], notes='Met at a workshop')
    response = authenticated_client.post('/api/hfl/entities/profile/' + m['id'], json=payload)
    assert response.status_code == 200
    assert response.json()['profile']['categories'] == ['Friends']
    assert any(n['label'] == 'Alex Tan' for n in entities.graph()['nodes'])
    corpus.clear()
    entities.enrich(use_model=False)
    entity = entities.entity_index()[0]
    assert entity['entries'] == [] and entity['profile']['notes'] == payload['notes']
    assert entity['profile']['emails'] == payload['emails']
    assert entities.entity_index(source='notes') == []


def test_profile_validation_and_owner_boundary(corpus, authenticated_client):
    from main import app
    with TestClient(app) as client:
        assert client.post('/api/hfl/entities/profile/entity:missing', json={'name': 'Alex'}).status_code == 401
    assert authenticated_client.post('/api/hfl/entities/profile/entity:missing', json={'name': 'Alex'}).status_code == 404
    for payload in [{'name': 'https://example.com'}, {'name': 'Alex', 'emails': ['invalid']}, {'name': 'Alex', 'phones': ['abc']}]:
        assert authenticated_client.post('/api/hfl/entities/profile/entity:missing', json=payload).status_code == 400


def test_merges_preserve_profiles_for_undo(corpus):
    store = get_store()
    for identity, name in [('a', 'Alex'), ('b', 'Alex Tan')]:
        store.save_profile(identity, 'people', dict(name=name, categories=[], emails=[], phones=[], notes=name))
    decision = store.merge('a', 'b', 'Verified identity')
    assert [e['id'] for e in entities.entity_index()] == ['b']
    assert len(store.profiles()) == 2
    store.undo(decision)
    assert {e['id'] for e in entities.entity_index()} == {'a', 'b'}
