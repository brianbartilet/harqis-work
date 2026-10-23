"""Incoming-only scheduling must not rebuild a historical backlog."""
import json

import pytest

from workflows.hfl.entity_store import get_store
from workflows.hfl.entity_resolution_scope import enqueue_affected, reassess_history


@pytest.fixture
def store(monkeypatch):
    monkeypatch.delenv('HARQIS_ENTITY_REASSESS_HISTORY', raising=False)
    return get_store()


def test_new_activity_queues_and_pending_edit_refreshes_revision(store):
    assert not reassess_history()
    store.save('new', 'v1', [], match=True)
    store.save('new', 'v2', [], match=True)
    with store.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT entry_id,revision FROM entity_resolution_jobs')] == [('new', 'v2')]


def test_cleared_or_completed_activity_is_not_requeued_by_reenrichment(store):
    store.save('old', 'v1', [], match=True)
    with store.connection() as db:
        db.execute('DELETE FROM entity_resolution_jobs')
    store.save('old', 'v2', [], match=True)
    store.save('incoming', 'v1', [], match=True)
    with store.connection() as db:
        assert [r[0] for r in db.execute('SELECT entry_id FROM entity_resolution_jobs')] == ['incoming']


def test_identity_changes_leave_history_unqueued_and_assignments_active(store):
    store.save('old', 'v1', [dict(id='person', label='Brian', kind='people')], match=True)
    with store.connection() as db:
        db.execute('DELETE FROM entity_resolution_jobs')
        db.execute('INSERT INTO entity_resolutions VALUES (?,?,?,?)',
                   ('old', 'person', 'person', json.dumps(dict(active=True))))
        assert enqueue_affected(db, ['person']) == 0
    store.save_profile('person', 'people', dict(name='Brian', notes='Updated'))
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM entity_resolution_jobs').fetchone()[0] == 0
        assert json.loads(db.execute('SELECT data FROM entity_resolutions').fetchone()[0])['active']
