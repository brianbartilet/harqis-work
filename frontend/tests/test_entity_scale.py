"""Scale regressions: candidate coverage, incremental indexes and durable storage."""
import json

from workflows.hfl.entity_candidates import CandidateIndex, candidates
from workflows.hfl.entity_store import get_store
from workflows.hfl.entity_run_storage import read_run, write_run


def row(identity, name='Alex Tan', kind='people'):
    return dict(id=identity, label=name, kind=kind, profile={},
                entries=[{'id': identity, 'source': 'notes'}])


def test_8400_exact_mentions_form_linear_review_star():
    rows = [row(f'e-{i:05d}') for i in range(8400)]
    pairs = candidates(rows)
    assert len(pairs) == 8399
    assert all('e-00000' in p for p in pairs)
    assert {i for p in pairs for i in p} == {r['id'] for r in rows}


def test_exact_buckets_respect_types_and_include_aliases():
    rows = [row('a'), row('b', 'Other'), row('c', kind='pets')]
    rows[1]['profile']['aliases'] = ['Alex Tan']
    assert candidates(rows, seeds={'b'}) == [('a', 'b')]


def test_persistent_features_update_and_remove(monkeypatch):
    from workflows.hfl import entity_candidates as module
    rows = [row('a'), row('b')]
    CandidateIndex(rows, persistent=True)
    original = module.search_features
    monkeypatch.setattr(module, 'search_features', lambda _: (_ for _ in ()).throw(AssertionError('recomputed')))
    assert candidates(rows, index=CandidateIndex(rows, persistent=True)) == [('a', 'b')]
    monkeypatch.setattr(module, 'search_features', original)
    rows[0]['label'] = 'Entirely different'
    index = CandidateIndex(rows[:1], persistent=True)
    assert index.names['a'] != {'alex tan'}
    with get_store().connection() as db:
        assert [r[0] for r in db.execute('SELECT id FROM entity_search_features')] == ['a']


def test_row_storage_migrates_legacy_and_deduplicates_evidence():
    evidence = {'id': 'a', 'activity': ['substantial source context']}
    run = {'id': 'legacy', 'state': 'running', 'pairs': {
        str(i): {'id': str(i), 'state': 'pending', 'left': evidence,
                 'right': {'id': str(i)}} for i in range(100)}}
    store = get_store()
    store.state('consolidation:legacy', run)
    with store.connection() as db:
        assert read_run(db, 'legacy') == run
        write_run(db, run)
        loaded = read_run(db, 'legacy')
        assert loaded.pop('storage_version') == 2
        assert loaded == run
        assert db.execute('SELECT count(*) FROM consolidation_evidence').fetchone()[0] == 101
        before = db.total_changes
        write_run(db, run)
        assert db.total_changes - before == 1  # metadata only; unchanged rows untouched
        run['pairs']['1']['state'] = 'deferred'
        before = db.total_changes
        write_run(db, run)
        assert db.total_changes - before == 2
        assert 'pairs' not in json.loads(db.execute('SELECT value FROM state').fetchone()[0])


def test_row_storage_rollback_preserves_previous_run():
    run = {'id': 'rollback', 'pairs': {'a': {'left': {'id': 'x'}, 'right': {'id': 'y'}, 'state': 'pending'}}}
    store = get_store()
    with store.connection() as db:
        write_run(db, run)
    try:
        with store.connection() as db:
            run['pairs']['a']['state'] = 'merged'
            write_run(db, run)
            raise RuntimeError('interrupted transaction')
    except RuntimeError:
        pass
    with store.connection() as db:
        assert read_run(db, 'rollback')['pairs']['a']['state'] == 'pending'


def test_status_read_keeps_one_snapshot_during_concurrent_save():
    store = get_store()
    run = {'id': 'concurrent', 'pairs': {'a': {'left': {'id': 'x'}, 'right': {'id': 'y'}, 'state': 'pending'}}}
    with store.connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        write_run(db, run)
    saved = []
    def concurrent_write(sql):
        if 'SELECT id,data FROM consolidation_evidence' in sql and not saved:
            saved.append(True)
            run['pairs']['a']['state'] = 'merged'
            with store.connection() as writer:
                write_run(writer, run)
    with store.connection() as reader:
        reader.set_trace_callback(concurrent_write)
        assert read_run(reader, 'concurrent')['pairs']['a']['state'] == 'pending'
    assert saved
    with store.connection() as db:
        assert read_run(db, 'concurrent')['pairs']['a']['state'] == 'merged'
