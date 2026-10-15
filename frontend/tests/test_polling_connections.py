"""Polling and corpus reads must release SQLite handles without waiting for GC."""
import sqlite3
from types import SimpleNamespace

import pytest

from modules.app_settings import store as settings
from modules.hfl_corpus.memory_pins import MemoryPinStore
from workflows.hfl.agent_bridge_store import AgentBridgeStore


@pytest.fixture
def captured_connections(monkeypatch):
    real_connect = sqlite3.connect
    captured = []

    def connect(*args, **kwargs):
        db = real_connect(*args, **kwargs)
        captured.append(db)
        return db

    monkeypatch.setattr(sqlite3, 'connect', connect)
    try:
        yield captured
    finally:
        for db in captured:
            db.close()


def assert_closed(connections):
    assert connections
    for db in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            db.execute('SELECT 1')


def test_settings_polling_closes_connections(tmp_path, monkeypatch, captured_connections):
    monkeypatch.setattr(settings, 'get_settings', lambda: SimpleNamespace(profile_store_path=tmp_path / 'profile.db'))
    settings.save_settings({'actions_polling_minutes': 5})
    for _ in range(30):
        assert settings.read_settings()['actions_polling_minutes'] == 5
    assert_closed(captured_connections)


@pytest.mark.parametrize('kind', ['settings', 'pins'])
def test_transaction_failure_rolls_back_and_closes(kind, tmp_path, monkeypatch, captured_connections):
    if kind == 'settings':
        monkeypatch.setattr(settings, 'get_settings', lambda: SimpleNamespace(profile_store_path=tmp_path / 'profile.db'))
        connect = settings.connection
    else:
        connect = MemoryPinStore(tmp_path / 'pins.db')._connect
    with connect() as db:
        db.execute('CREATE TABLE closure_probe(value TEXT)')
    with pytest.raises(RuntimeError, match='abort'):
        with connect() as db:
            db.execute("INSERT INTO closure_probe VALUES ('discard')")
            raise RuntimeError('abort')
    with connect() as db:
        assert db.execute('SELECT count(*) FROM closure_probe').fetchone()[0] == 0
    assert_closed(captured_connections)


@pytest.mark.parametrize('malformed', [False, True])
def test_pin_snapshot_closes_main_and_bridge_connections(tmp_path, monkeypatch, captured_connections, malformed):
    bridge_path = tmp_path / 'bridge.db'
    monkeypatch.setenv('HFL_AGENT_BRIDGE_STORE_PATH', str(bridge_path))
    bridge = AgentBridgeStore(bridge_path)
    if malformed:
        with bridge.connect() as db:
            db.execute('DROP TABLE agent_subscriptions')
            db.execute('CREATE TABLE agent_subscriptions(unexpected TEXT)')
    pins = MemoryPinStore(tmp_path / 'pins.db')
    for _ in range(30):
        if malformed:
            with pytest.raises(sqlite3.OperationalError, match='no such column'):
                pins.snapshot()
        else:
            assert pins.snapshot()['ranges'] == []
    assert_closed(captured_connections)
