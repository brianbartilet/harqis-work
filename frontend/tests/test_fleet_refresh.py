"""Regression coverage for attribution and bounded shared corpus reads."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest


def test_receipt_attribution_ignores_examples_and_nested_payloads():
    from modules.agents.corpus_projection import receipt_owner
    from workflows.hfl.dto import HflEntry
    agents = [{'id': 'ada', 'name': 'Ada'}, {'id': 'leo', 'name': 'Leo'}]
    def owner(text, source='agents-activity'):
        return receipt_owner({'source': source, 'text': text}, agents)
    assert owner('{"agent_id":"ada"}', 'manual-entry') is None
    assert owner('Example: {"agent_id":"ada"}') is None
    assert owner('{"output":{"agent_id":"ada"}}') is None
    assert owner(json.dumps({'agent_id': 'leo', 'output': {'agent_id': 'ada'}})) == 'leo'
    assert owner('{"agent_id":"missing","agent_name":"Ada"}') is None
    assert owner('{"agent_name":"Ada"}') == 'ada'
    assert owner('[]') is None
    receipt = HflEntry(when=None, what_happened=json.dumps({'agent_id': 'ada', 'output': 'quoted "agent_id":"leo"'}))
    assert owner(receipt.to_markdown()) == 'ada'
    agents.append({'id': 'duplicate', 'name': 'Ada'})
    assert owner('{"agent_name":"Ada"}') is None


@pytest.fixture
def entry_cache(monkeypatch):
    from modules.hfl_corpus import fleet_entry_cache as cache, entities
    monkeypatch.setattr(cache, '_key', None)
    monkeypatch.setattr(cache, '_entries', None)
    monkeypatch.setattr(cache, '_expires', 0)
    clock = [100.0]
    key = ['owner-permissions-v1']
    monkeypatch.setattr(cache, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(cache, 'context_key', lambda: key[0])
    return cache, entities, clock, key


def test_cache_coalesces_concurrent_reads(entry_cache, monkeypatch):
    cache, entities, _, _ = entry_cache
    started, release = Event(), Event()
    calls = []
    def scan():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return [{'id': 'entry'}]
    monkeypatch.setattr(entities, 'current_entries', scan)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(cache.current_entries) for _ in range(8)]
        assert started.wait(5)
        release.set()
        assert all(f.result() == [{'id': 'entry'}] for f in futures)
    assert len(calls) == 1


def test_cache_expires_and_invalidates_permissions_without_stale_fallback(entry_cache, monkeypatch):
    cache, entities, clock, key = entry_cache
    calls = []
    def scan():
        calls.append(1)
        return [{'id': str(len(calls))}]
    monkeypatch.setattr(entities, 'current_entries', scan)
    assert cache.current_entries() == [{'id': '1'}]
    clock[0] += 29
    assert cache.current_entries() == [{'id': '1'}]
    key[0] = 'owner-permissions-v2'
    assert cache.current_entries() == [{'id': '2'}]
    clock[0] += 30
    assert cache.current_entries() == [{'id': '3'}]
    clock[0] += 30
    def fail():
        raise RuntimeError('Corpus offline')
    monkeypatch.setattr(entities, 'current_entries', fail)
    with pytest.raises(RuntimeError, match='Corpus offline'):
        cache.current_entries()


def test_snapshot_records_stay_live_with_cached_entries(entry_cache, monkeypatch):
    from modules.agents import corpus_projection
    from modules.hfl_corpus import ideas_api
    cache, entities, _, _ = entry_cache
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    calls = []
    monkeypatch.setattr(entities, 'current_entries', lambda: calls.append(1) or [])
    state = {'status': 'open'}
    monkeypatch.setattr(ideas_api, 'permitted_snapshot', lambda entries, **kw: dict(state))
    assert corpus_projection.read()[0]['status'] == 'open'
    state['status'] = 'done'
    assert corpus_projection.read()[0]['status'] == 'done'
    assert len(calls) == 1
