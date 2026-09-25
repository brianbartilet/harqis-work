"""Completeness regressions using only synthetic source/spool data."""
import json
from datetime import timedelta

from scripts.agents.hfl import collect_hermes_sessions as capture
from scripts.tests.test_collect_hermes_sessions import run_collection


def test_approval_later_run_appends_linked_answer_without_rewriting(database, tmp_path, monkeypatch):
    root = tmp_path / 'audit'
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(root))
    message(database, 1, 'user', 'Publish the tested change')
    message(database, 2, 'assistant', 'Do you approve publication?', finish_reason='stop')
    assert run_collection(database)['spooled'] == 1
    path, = root.glob('events/*/*.json')
    first = json.loads(path.read_text())
    first['ingest'] = {'entry_id': 'ack', 'delivery': 'persisted'}
    path.write_text(json.dumps(first))
    before = path.read_bytes()
    message(database, 3, 'user', 'yes')
    message(database, 4, 'assistant', 'Published the change', finish_reason='stop')
    assert run_collection(database)['spooled'] == 1
    assert path.read_bytes() == before
    events = [json.loads(p.read_text()) for p in root.glob('events/*/*.json')]
    followup, = [e for e in events if e['event_id'] != first['event_id']]
    assert followup['related_event_id'] == first['event_id']
    assert followup['assistant_outcome'] == 'Published the change'
    assert run_collection(database)['spooled'] == 0

from scripts.tests.test_collect_hermes_sessions import (database, message, pairs, NOW)


def test_late_answer_recovers_prompt_outside_window_and_compaction(database):
    message(database, 1, 'user', 'Preserve historical request',
            timestamp=(NOW-timedelta(days=3)).timestamp(), active=0, compacted=1)
    message(database, 2, 'assistant', 'Historical answer', finish_reason='stop',
            timestamp=(NOW-timedelta(days=2)).timestamp(), active=0, compacted=1)
    message(database, 3, 'user', 'yes')
    message(database, 4, 'assistant', 'Late completion', finish_reason='stop')
    result = pairs(database)
    assert len(result) == 1
    assert result[0]['prompt_id'] == '1'
    assert result[0]['assistant_outcome'] == 'Late completion'
    assert result[0]['related_event_id']


def test_pending_and_interrupted_inventory_retained_then_final_converges(database, tmp_path, monkeypatch):
    root = tmp_path / 'audit'
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(root))
    message(database, 1, 'user', 'Investigate password=privatevalue')
    message(database, 2, 'user', '/stop')
    message(database, 3, 'user', 'Retain unanswered requirement')
    result = run_collection(database)
    assert result['inventory_written'] == 2
    inventory = [json.loads(p.read_text()) for p in root.glob('prompt-inventory/*/*.json')]
    assert {e['prompt_id']: e['capture_state'] for e in inventory} == {'1': 'interrupted', '3': 'pending'}
    assert all(e['assistant_outcome'] == '' for e in inventory)
    assert 'privatevalue' not in json.dumps(inventory)
    before = {p: p.read_bytes() for p in root.glob('prompt-inventory/*/*.json')}
    message(database, 4, 'assistant', 'Requirement addressed', finish_reason='stop')
    result = run_collection(database)
    assert result['spooled'] == 1
    assert all(p.read_bytes() == raw for p, raw in before.items())
    inventory = [json.loads(p.read_text()) for p in root.glob('prompt-inventory/*/*.json')]
    assert any(e['prompt_id'] == '3' and e['capture_state'] == 'answered' for e in inventory)
    assert run_collection(database)['inventory_written'] == 0


def test_compaction_batch_uses_original_ids_but_preserves_real_retries(database):
    for ident in (1, 3):
        message(database, ident, 'user', 'Repeat real request', active=0, compacted=1,
                timestamp=NOW.timestamp()-100+ident)
        message(database, ident+1, 'assistant', 'Visible answer', finish_reason='stop',
                active=0, compacted=1, timestamp=NOW.timestamp()-100+ident+1)
    for offset, (role, text) in enumerate([
        ('user', 'Repeat real request'), ('assistant', 'Visible answer'),
        ('user', 'Repeat real request'), ('assistant', 'Visible answer')]):
        message(database, 10+offset, role, text, timestamp=NOW.timestamp()-10+offset*1e-6,
                finish_reason='stop' if role == 'assistant' else None)
    message(database, 20, 'user', 'Repeat real request', timestamp=NOW.timestamp()-5)
    message(database, 21, 'assistant', 'New answer', finish_reason='stop', timestamp=NOW.timestamp()-4)
    assert [e['prompt_id'] for e in pairs(database)] == ['1', '3', '20']


def test_unanswered_prompts_enter_hfl_spool_and_late_answer_is_linked(database, tmp_path, monkeypatch):
    root = tmp_path / 'audit'
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(root))
    message(database, 1, 'user', 'Investigate missing captures')
    result = run_collection(database)
    assert result['spooled'] == 1
    path, = root.glob('events/*/*.json')
    first = json.loads(path.read_text())
    assert first['result_status'] == 'pending'
    assert first['assistant_outcome'] == ''
    before = path.read_bytes()
    message(database, 2, 'assistant', 'Found the sync fault', finish_reason='stop')
    assert run_collection(database)['spooled'] == 1
    assert path.read_bytes() == before
    revision, = [json.loads(p.read_text()) for p in root.glob('events/*/*.json') if p != path]
    assert revision['related_event_id'] == first['event_id']
    assert revision['assistant_outcome'] == 'Found the sync fault'
    assert run_collection(database)['spooled'] == 0


def test_new_request_after_unfinished_assistant_does_not_borrow_later_answer(database, tmp_path, monkeypatch):
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(tmp_path))
    message(database, 1, 'user', 'Investigate first problem')
    message(database, 2, 'assistant', 'Checking first problem', finish_reason=None)
    message(database, 3, 'user', 'Investigate second problem')
    message(database, 4, 'assistant', 'Second problem fixed', finish_reason='stop')
    run_collection(database)
    events = [json.loads(p.read_text()) for p in tmp_path.glob('events/*/*.json')]
    first, = [e for e in events if e['prompt_id'] == '1']
    assert first['assistant_outcome'] == ''
    assert first['result_status'] == 'interrupted'
    second, = [e for e in events if e['prompt_id'] == '3']
    assert second['assistant_outcome'] == 'Second problem fixed'


def test_historical_pending_snapshot_does_not_regress_retained_answer(database, tmp_path, monkeypatch):
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(tmp_path))
    message(database, 1, 'user', 'Check capture', timestamp=NOW.timestamp()-10)
    message(database, 2, 'assistant', 'Capture checked', finish_reason='stop', timestamp=NOW.timestamp()-1)
    assert run_collection(database)['spooled'] == 1
    result = capture.collect(database, since=NOW-timedelta(days=1), until=NOW-timedelta(seconds=5))
    assert result['spooled'] == 0


def test_cross_window_interruption_preserves_pending_and_appends_once(database, tmp_path, monkeypatch):
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(tmp_path))
    old = NOW - timedelta(days=3)
    message(database, 1, 'user', 'Investigate earlier request', timestamp=old.timestamp())
    message(database, 2, 'assistant', 'Investigation started', timestamp=old.timestamp()+1)
    assert capture.collect(database, since=old-timedelta(hours=1),
                           until=old+timedelta(hours=1))['spooled'] == 1
    path, = tmp_path.glob('events/*/*.json')
    original = path.read_bytes()
    original_id = json.loads(original)['event_id']
    message(database, 3, 'user', 'Investigate next request', timestamp=NOW.timestamp()-2)
    message(database, 4, 'assistant', 'Next request answered',
            timestamp=NOW.timestamp()-1, finish_reason='stop')
    assert run_collection(database)['spooled'] == 2
    assert path.read_bytes() == original
    revision, = [json.loads(p.read_text()) for p in tmp_path.glob('events/*/*.json')
                 if p != path and json.loads(p.read_text())['prompt_id'] == '1']
    assert revision['related_event_id'] == original_id
    assert revision['result_status'] == 'interrupted'
    assert revision['observation_id'] == '3'
    assert revision['assistant_outcome'] == ''
    assert run_collection(database)['spooled'] == 0
    assert path.read_bytes() == original


def test_capture_writer_preserves_acknowledged_winner(tmp_path, monkeypatch):
    from scripts.agents.hfl.capture_session_event import normalize_event, write_event
    monkeypatch.setenv('HFL_SESSION_AUDIT_PATH', str(tmp_path))
    stale = normalize_event(dict(surface='hermes', session_id='s', prompt_id='1',
                                original_prompt='Fix it', assistant_outcome='Done'))
    acknowledged = {**stale, 'ingest': {'entry_id': 'winner', 'delivery': 'persisted'}}
    path = write_event(acknowledged)
    before = path.read_bytes()
    write_event(stale)
    assert path.read_bytes() == before


def test_consecutive_requirements_and_internal_reminder_survive(database):
    message(database, 1, 'user', 'Fix parser')
    message(database, 2, 'user', 'Also retain Unicode support')
    message(database, 3, 'user', '[System: verify before completing]')
    message(database, 4, 'assistant', 'Fixed parser with Unicode support', finish_reason='stop')
    events = pairs(database)
    assert [e['prompt_id'] for e in events] == ['1', '2']
    assert all(e['assistant_outcome'] == 'Fixed parser with Unicode support' for e in events)
    assert '[System:' not in json.dumps(events)
