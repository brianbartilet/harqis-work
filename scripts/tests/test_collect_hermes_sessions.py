"""Hermes collector contracts; all databases and spools are synthetic."""
import importlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from scripts.agents.hfl.capture_session_event import normalize_event

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)


def collector():
    return importlib.import_module("scripts.agents.hfl.collect_hermes_sessions")


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT,
                ended_at REAL, parent_session_id TEXT, profile_name TEXT);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT,
                role TEXT, content TEXT, timestamp REAL, tool_calls TEXT,
                finish_reason TEXT, codex_message_items TEXT,
                active INTEGER DEFAULT 1, compacted INTEGER DEFAULT 0);
        """)
        db.execute("INSERT INTO sessions VALUES ('s', 'cli', ?, NULL, NULL)", (NOW.timestamp(),))
    return path


def message(database, ident, role, content, **kw):
    values = dict(id=ident, session_id="s", role=role, content=content,
                  timestamp=(NOW - timedelta(minutes=5)).timestamp())
    values.update(kw)
    with sqlite3.connect(database) as db:
        db.execute(f"INSERT INTO messages ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))


def pairs(database):
    return list(collector().iter_completed_pairs(database, since=NOW-timedelta(days=1), until=NOW))


@pytest.mark.parametrize('session_update,prompt,answer_fields', [
    ("ended_at=NULL", "Fix parser", {'finish_reason': 'tool_calls'}),
    ("source='cron'", "Fix parser", {}),
    ("parent_session_id='parent'", "Fix parser", {}),
    ("profile_name='work'", "Fix parser", {}),
    (None, "[System: verify your result]", {}),
    (None, "/stop", {}),
    (None, "thanks", {}),
    (None, "Fix parser", {'codex_message_items': '[{"type":"message","phase":"commentary"}]'}),
    (None, "Fix parser", {'codex_message_items': 'malformed'}),
    (None, "Fix parser", {'finish_reason': 'incomplete'}),
    (None, "Fix parser", {'finish_reason': None}),
    (None, "Fix parser", {'active': 0}),
    (None, "Fix parser", {'compacted': 1}),
])
def test_excludes_non_user_facing_or_unfinished_turns(database, session_update, prompt, answer_fields):
    if session_update:
        with sqlite3.connect(database) as db:
            db.execute('UPDATE sessions SET ' + session_update)
    message(database, 1, 'user', prompt)
    message(database, 2, 'assistant', 'Not a final answer', **dict({'finish_reason': 'stop'}, **answer_fields))
    assert pairs(database) == []


def run_collection(database, **kwargs):
    return collector().collect(database, since=NOW-timedelta(days=1), until=NOW, **kwargs)


def test_spools_before_retry_and_never_rewrites_duplicate_checkpoint(database, tmp_path, monkeypatch):
    root = tmp_path / 'audit'
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(root))
    message(database, 1, 'user', 'Fix parser')
    message(database, 2, 'assistant', 'Fixed', finish_reason='stop')
    assert run_collection(database)['spooled'] == 1
    path, = root.glob('events/*/*.json')
    event = json.loads(path.read_text())
    assert event['ingest'] == {}
    event['ingest'] = {'entry_id': 'persisted', 'delivery': 'persisted'}
    path.write_text(json.dumps(event))
    original = path.read_bytes()
    assert run_collection(database)['duplicates'] == 1
    assert path.read_bytes() == original


def test_bounded_batch_skips_duplicates_and_revisits_late_closed_session(database, tmp_path, monkeypatch):
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(tmp_path / 'audit'))
    for ident in (1, 3, 5):
        message(database, ident, 'user', f'Fix parser {ident}')
        message(database, ident+1, 'assistant', 'Fixed', finish_reason='stop')
    assert run_collection(database, limit=1)['spooled'] == 1
    assert run_collection(database, limit=1)['spooled'] == 1
    assert run_collection(database, limit=1)['spooled'] == 1
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO sessions VALUES ('late', 'telegram', NULL, NULL, 'default')")
    message(database, 7, 'user', 'Late request', session_id='late')
    message(database, 8, 'assistant', 'Late answer', session_id='late', finish_reason=None)
    assert run_collection(database, limit=1)['spooled'] == 0
    with sqlite3.connect(database) as db:
        db.execute("UPDATE messages SET finish_reason='stop' WHERE id=8")
        db.execute("UPDATE sessions SET ended_at=? WHERE id='late'", (NOW.timestamp(),))
    assert run_collection(database, limit=1)['spooled'] == 1


@pytest.mark.parametrize('corrupt', ['{', '[]', '{}', '{"ingest": []}'])
def test_malformed_existing_event_fails_closed(database, tmp_path, monkeypatch, corrupt):
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(tmp_path / 'audit'))
    message(database, 1, 'user', 'Fix parser')
    message(database, 2, 'assistant', 'Fixed', finish_reason='stop')
    run_collection(database)
    path, = (tmp_path / 'audit').glob('events/*/*.json')
    path.write_text(corrupt)
    with pytest.raises(ValueError):
        run_collection(database)
    assert path.read_text() == corrupt


def test_dry_run_is_count_only_without_creating_spool(database, tmp_path, monkeypatch):
    root = tmp_path / 'absent'
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(root))
    message(database, 1, 'user', 'Private request')
    message(database, 2, 'assistant', 'Private answer', finish_reason='stop')
    result = run_collection(database, dry_run=True)
    assert result['eligible'] == 1
    assert result['spooled'] == 0
    assert 'Private' not in json.dumps(result)
    assert not root.exists()


@pytest.mark.parametrize('since,until,limit', [
    (NOW, NOW-timedelta(seconds=1), 10),
    (NOW-timedelta(days=15), NOW, 10),
    (NOW.replace(tzinfo=None), NOW, 10),
    (NOW-timedelta(days=1), NOW, 0),
    (NOW-timedelta(days=1), NOW, 501),
])
def test_invalid_bounds_fail_before_writing(database, tmp_path, monkeypatch, since, until, limit):
    root = tmp_path / 'absent'
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(root))
    with pytest.raises(ValueError):
        collector().collect(database, since=since, until=until, limit=limit)
    assert not root.exists()


def test_concurrent_collector_fails_without_writing(database, tmp_path, monkeypatch):
    import fcntl
    root = tmp_path / 'audit'
    root.mkdir()
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(root))
    message(database, 1, 'user', 'Fix parser')
    message(database, 2, 'assistant', 'Fixed', finish_reason='stop')
    with (root / '.hermes-collector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            run_collection(database)
        assert not (root / 'events').exists()
    assert run_collection(database)['spooled'] == 1


@pytest.fixture
def cli_env(database, tmp_path, monkeypatch):
    module = collector()
    from scripts import launch
    monkeypatch.setattr(launch, 'setup_env', lambda: None)
    monkeypatch.setattr(module, 'DEFAULT_DB', database, raising=False)
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(tmp_path / 'audit'))
    monkeypatch.delenv('HFL_HERMES_CAPTURE_SINCE', raising=False)
    return module


def test_cli_requires_launch_boundary_and_reports_errors_without_payload(cli_env, capsys):
    assert cli_env.main([]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {'failed': 1, 'error_type': 'ValueError'}


def test_cli_explicit_preview_bootstraps_env_and_prints_counts(cli_env, database, capsys, monkeypatch):
    from scripts import launch
    called = []
    monkeypatch.setattr(launch, 'setup_env', lambda: called.append(True))
    message(database, 1, 'user', 'Secret request')
    message(database, 2, 'assistant', 'Secret answer', finish_reason='stop')
    assert cli_env.main(['--since', (NOW-timedelta(days=1)).isoformat(), '--until', NOW.isoformat(), '--dry-run']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['eligible'] == 1 and output['spooled'] == 0
    assert called == [True]
    assert 'Secret' not in json.dumps(output)


def test_retry_window_covers_collector_overlap():
    # Inspect the literal config without importing Celery or contacting any service.
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'workflows/hfl/tasks_config.py').read_text())
    retry = next(node.values[i] for node in ast.walk(tree) if isinstance(node, ast.Dict)
                 for i, key in enumerate(node.keys)
                 if isinstance(key, ast.Constant) and key.value == 'run-job--ingest_agent_session_events')
    kwargs = next(value for key, value in zip(retry.keys, retry.values) if isinstance(key, ast.Constant) and key.value == 'kwargs')
    assert ast.literal_eval(kwargs)['window_days'] > collector().LOOKBACK_DAYS


def test_completed_final_answer_in_open_session_is_captured(database):
    with sqlite3.connect(database) as db:
        db.execute('UPDATE sessions SET ended_at=NULL')
    message(database, 1, 'user', 'Fix parser')
    message(database, 2, 'assistant', 'Fixed parser', finish_reason='stop')
    assert len(pairs(database)) == 1



def test_terminal_answer_not_pretool_commentary_and_legacy_id(database):
    message(database, 1, "user", "Fix parser password=supersecret")
    message(database, 2, "assistant", "I will inspect", finish_reason="tool_calls", tool_calls='[{"name":"terminal"}]')
    message(database, 3, "tool", "private tool output")
    message(database, 4, "assistant", "Fixed parser", finish_reason="stop")
    result = pairs(database)
    assert len(result) == 1
    assert result[0]["assistant_outcome"] == "Fixed parser"
    legacy = normalize_event(dict(surface="hermes", session_id="s", prompt_id="1", original_prompt="Fix parser password=supersecret"))
    assert result[0]["event_id"] == legacy["event_id"]
    assert "supersecret" not in json.dumps(result)
