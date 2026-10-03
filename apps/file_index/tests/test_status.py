import pytest

from apps.file_index.store import Store
from apps.file_index.status import indexing_status
from apps.file_index import service


def test_coverage_and_schedule(tmp_path, monkeypatch):
    monkeypatch.setenv('FILES_ENABLED', '1')
    store = Store(tmp_path / 'catalog.db')
    source = store.add('sources', {'name': 'Docs', 'kind': 'local', 'enabled': True,
                                  'interval_hours': 2, 'last_scan': 100, 'last_queued': 200})
    assert indexing_status(store, [source])['coverage']['indexed_percent'] is None
    file = store.observe(source, 'one', {'name': 'one'}, 'run')
    store.observe(source, 'other', {'name': 'one'}, 'run', file_id=file['id'])
    store.patch('files', file['id'], {'categories': ['1', '2']})
    store.observe(source, 'reference', {'name': 'reference'}, None, observed=False)
    status = indexing_status(store, [source])
    assert status['coverage'] == {'total': 2, 'indexed': 1, 'categorized': 1,
                                   'indexed_percent': 50, 'categorized_percent': 50}
    assert status['locations'][0]['next_due'] == 7400
    legacy = {**source, 'state': 'unreachable', 'count': None}
    assert indexing_status(store, [legacy])['locations'][0]['processed'] == 0
    store.event(source['id'], 'scan_failed', count=197)
    assert indexing_status(store, [legacy])['locations'][0]['processed'] == 197
    assert indexing_status(store, [{**legacy, 'processed': 0}])['locations'][0]['processed'] == 0
    for changes in ({'enabled': False}, {'configured_available': False}, {'kind': 'ftp'}):
        assert indexing_status(store, [{**source, **changes}])['locations'][0]['next_due'] is None
    monkeypatch.setenv('FILES_ENABLED', '0')
    assert indexing_status(store, [source])['locations'][0]['schedule'] == 'disabled'


def test_live_progress_failure_and_recovery(tmp_path, monkeypatch):
    store = Store(tmp_path / 'catalog.db')
    source = store.add('sources', {'name': 'Docs', 'kind': 'http', 'enabled': True})

    def discover(_):
        for index in range(101):
            if index == 100:
                current = store.get('sources', source['id'])
                assert current['processed'] == 100
                assert current['finished_at'] is None
                assert indexing_status(store, [current])['locations'][0]['state'] == 'scanning'
            yield str(index), {'name': str(index)}
        raise OSError('connection lost')

    monkeypatch.setattr(service.adapters, 'discover', discover)
    with pytest.raises(OSError):
        service.scan(source['id'], store)
    failed = store.get('sources', source['id'])
    assert failed['processed'] == 101
    assert failed['finished_at'] >= failed['started_at']
    assert failed['last_scan'] is None
    monkeypatch.setattr(service.adapters, 'discover', lambda _: iter([('0', {'name': '0'})]))
    service.scan(source['id'], store)
    ready = store.get('sources', source['id'])
    assert ready['processed'] == 1 and ready['state'] == 'ready'
    assert ready['last_scan'] is not None
    store.patch('sources', source['id'], {'state': 'scanning'})
    assert indexing_status(store, store.all('sources'))['locations'][0]['state'] == 'interrupted'
