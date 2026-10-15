"""Connection lifetime must not depend on cyclic garbage collection."""
import sqlite3

import pytest

from workflows.hfl.action_agent_store import ActionAgentStore
from workflows.hfl.agent_bridge_store import AgentBridgeStore


@pytest.mark.parametrize('store_type', [AgentBridgeStore, ActionAgentStore])
def test_connection_commits_and_closes(store_type, tmp_path):
    store = store_type(tmp_path / 'bridge.sqlite3')
    with store.connect() as db:
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        db.execute('INSERT INTO agent_dispatch_state VALUES (?, ?)', ('test', 'committed'))
    # Retain the real connection so GC cannot conceal a leaked handle.
    try:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            db.execute('SELECT 1')
        with store.connect() as check:
            assert check.execute('SELECT value FROM agent_dispatch_state').fetchone()['value'] == 'committed'
    finally:
        db.close()


@pytest.mark.parametrize('store_type', [AgentBridgeStore, ActionAgentStore])
def test_connection_rolls_back_and_closes_on_exception(store_type, tmp_path):
    store = store_type(tmp_path / 'bridge.sqlite3')
    with pytest.raises(RuntimeError, match='abort'):
        with store.connect() as db:
            db.execute('INSERT INTO agent_dispatch_state VALUES (?, ?)', ('test', 'rollback'))
            raise RuntimeError('abort')
    try:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            db.execute('SELECT 1')
        with store.connect() as check:
            assert check.execute('SELECT count(*) FROM agent_dispatch_state').fetchone()[0] == 0
    finally:
        db.close()


@pytest.mark.parametrize('store_type', [AgentBridgeStore, ActionAgentStore])
def test_connection_closes_when_commit_fails(store_type, tmp_path):
    store = store_type(tmp_path / 'bridge.sqlite3')
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as db:
            db.execute('PRAGMA defer_foreign_keys=ON')
            db.execute('INSERT INTO agent_artifacts VALUES (?, ?, ?, ?)', ('missing', 'test', 'digest', 0))
    try:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            db.execute('SELECT 1')
        with store.connect() as check:
            assert check.execute('SELECT count(*) FROM agent_artifacts').fetchone()[0] == 0
    finally:
        db.close()


@pytest.mark.parametrize('store_type', [AgentBridgeStore, ActionAgentStore])
def test_repeated_store_operations_close_every_connection(store_type, tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    connections = []

    def tracked_connect(*args, **kwargs):
        db = real_connect(*args, **kwargs)
        connections.append(db)  # Strong references make this independent of GC.
        return db

    monkeypatch.setattr(sqlite3, 'connect', tracked_connect)
    try:
        for _ in range(30):
            store = store_type(tmp_path / 'bridge.sqlite3')
            assert store.list() == []
            assert store.subscriptions() == []
            with pytest.raises(KeyError):
                store.get('missing')
            if isinstance(store, ActionAgentStore):
                assert store.configs() == {}
                assert store.sessions() == []
                assert store.read_io('missing', 'out') == []
        assert len(connections) >= 120
        for db in connections:
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                db.execute('SELECT 1')
    finally:
        for db in connections:
            db.close()


def test_connection_closes_when_setup_fails(tmp_path, monkeypatch):
    store = AgentBridgeStore(tmp_path / 'bridge.sqlite3')
    real_connect = sqlite3.connect
    connections = []

    class SetupFailure(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == 'PRAGMA foreign_keys=ON':
                raise sqlite3.OperationalError('setup failed')
            return super().execute(sql, *args)

    def failing_connect(*args, **kwargs):
        db = real_connect(*args, **kwargs, factory=SetupFailure)
        connections.append(db)
        return db

    monkeypatch.setattr(sqlite3, 'connect', failing_connect)
    try:
        with pytest.raises(sqlite3.OperationalError, match='setup failed'):
            with store.connect():
                pytest.fail('setup should fail before yielding')
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connections[0].execute('SELECT 1')
    finally:
        for db in connections:
            db.close()
