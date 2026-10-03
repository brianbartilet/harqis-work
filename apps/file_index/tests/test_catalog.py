"""Isolated filesystem integration and failure/recovery contract tests."""
import json
import time
from pathlib import Path

import pytest

from apps.file_index import adapters, service
from apps.file_index.store import Store, identity


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    root = tmp_path / 'documents'
    root.mkdir()
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(root)]))
    monkeypatch.setenv('FILES_HOST_ID', 'test-host')
    store = Store(tmp_path / 'catalog.sqlite3')
    source = store.add('sources', {'name': 'Documents', 'kind': 'local', 'root': str(root),
        'host': 'test-host', 'enabled': True, 'categories': ['1'], 'tags': ['project'], 'interval_hours': 24})
    return store, source, root


def test_scan_update_missing_and_recovery(catalog):
    store, source, root = catalog
    file = root / 'brief.txt'
    file.write_text('first')
    service.scan(source['id'], store)
    first = store.catalog()['items'][0]
    file.write_text('second version')
    service.scan(source['id'], store)
    result = store.catalog()
    assert result['total'] == 1
    assert result['items'][0]['id'] == first['id']
    assert result['items'][0]['size'] == len('second version')
    assert result['items'][0]['categories'] == ['1']
    file.unlink()
    service.scan(source['id'], store)
    assert store.locations(first['id'])[0]['status'] == 'missing'
    file.write_text('restored')
    service.scan(source['id'], store)
    assert store.locations(first['id'])[0]['status'] == 'available'


def test_incomplete_scan_does_not_mark_missing(catalog, monkeypatch):
    store, source, root = catalog
    (root / 'brief.txt').write_text('keep')
    service.scan(source['id'], store)
    def fail(_):
        raise PermissionError('offline')
        yield
    monkeypatch.setattr(adapters, 'discover', fail)
    with pytest.raises(PermissionError):
        service.scan(source['id'], store)
    assert store.catalog()['items'][0]['locations'][0]['status'] == 'available'
    assert store.get('sources', source['id'])['state'] == 'permission_denied'


def test_retrieval_limits_and_root_boundaries(catalog, tmp_path, monkeypatch):
    store, source, root = catalog
    (root / 'brief.txt').write_text('secret data')
    service.scan(source['id'], store)
    file = store.catalog()['items'][0]
    destination = tmp_path / 'download'
    result = service.retrieve_file(file['id'], destination, store)
    assert destination.read_text() == 'secret data'
    assert len(result['sha256']) == 64
    assert store.get('files', file['id'])['last_downloaded']
    with pytest.raises(PermissionError):
        adapters.local_path(source, tmp_path / 'outside')
    with pytest.raises(OSError):
        adapters.local_path({**source, 'host': 'other-host'})
    monkeypatch.setenv('FILES_MAX_BYTES', '2')
    with pytest.raises(OSError):
        service.retrieve_file(file['id'], destination, store)


class DriveDouble:
    """Deterministic provider boundary; never touches a live Drive account."""
    def __init__(self):
        self.objects = {}
        self.public = set()
        self.fail_share = False
    def allocate_id(self):
        return identity()
    def package_object(self, object_id, name, **kwargs):
        if object_id not in self.objects:
            self.objects[object_id] = {'id': object_id, 'name': name,
                'bytes': Path(kwargs['path']).read_bytes() if kwargs.get('path') else None}
        return self.objects[object_id]
    def get_file(self, object_id, **kwargs):
        return self.objects[object_id]
    def public_reader(self, object_id):
        self.public.add(object_id)
        if self.fail_share:
            raise OSError('lost response')
        return 'anyone'
    def revoke_public_reader(self, object_id):
        self.public.discard(object_id)


def make_revision(catalog):
    store, source, root = catalog
    (root / 'brief.txt').write_text('immutable content')
    service.scan(source['id'], store)
    file_id = store.catalog()['items'][0]['id']
    package = store.add('packages', {'title': 'Brief', 'description': 'Review', 'expiry_days': 7})
    revision = store.revision(package['id'], [file_id], 'owner', identity())
    return store, package, revision, file_id


def test_publish_retry_history_and_expiry(catalog):
    store, package, revision, file_id = make_revision(catalog)
    drive = DriveDouble()
    drive.fail_share = True
    with pytest.raises(OSError):
        service.publish(revision['id'], store, drive)
    failed = store.get('revisions', revision['id'])
    assert failed['expires_at']
    with pytest.raises(KeyError):
        store.guest(failed['token'])
    drive.fail_share = False
    service.publish(revision['id'], store, drive)
    service.publish(revision['id'], store, drive)
    assert len(drive.objects) == 2
    published = store.guest(revision['token'])
    (catalog[2] / 'brief.txt').write_text('new source content')
    assert drive.objects[published['copies'][file_id]['drive_id']]['bytes'] == b'immutable content'
    next_revision = store.revision(package['id'], [file_id], 'owner', identity())
    assert next_revision['number'] == 2
    published['expires_at'] = time.time() - 1
    store.put('revisions', published)
    with pytest.raises(KeyError):
        store.guest(revision['token'])
    assert service.expire(store, drive)['expired'] == 1
    assert not drive.public
    assert store.get('revisions', revision['id'])['state'] == 'expired'


def test_revision_idempotency_and_publication_failure(catalog):
    store, package, revision, file_id = make_revision(catalog)
    assert store.revision(package['id'], [file_id], 'owner', revision['id'])['id'] == revision['id']
    other = store.add('packages', {'title': 'Other', 'description': '', 'expiry_days': 7})
    with pytest.raises(ValueError):
        store.revision(other['id'], [file_id], 'owner', revision['id'])
    (catalog[2] / 'brief.txt').unlink()
    drive = DriveDouble()
    with pytest.raises(OSError):
        service.publish(revision['id'], store, drive)
    assert not drive.public
    assert store.get('revisions', revision['id'])['state'] == 'failed'


def test_manual_location_does_not_overwrite_identity(catalog):
    store, source, root = catalog
    (root / 'brief.txt').write_text('one')
    service.scan(source['id'], store)
    file = store.catalog()['items'][0]
    store.observe(source, str(root / 'copy.txt'), file, 'manual', file_id=file['id'])
    locations = store.locations(file['id'])
    assert len(locations) == 2
    assert len({l['id'] for l in locations}) == 2
    assert all(l['id'] != file['id'] for l in locations)


def test_output_registration_respects_roots(catalog, tmp_path):
    store, source, root = catalog
    path = root / 'generated.pdf'
    path.write_bytes(b'output')
    item = service.register_output(path, {'task': 'test.generate'}, store)
    assert item['provenance']['task'] == 'test.generate'
    assert service.register_output(tmp_path / 'outside', {}, store) is None


def test_http_rejects_private_credentials_and_redirects(monkeypatch):
    for url in ['http://127.0.0.1/private', 'http://user:pass@example.com/a', 'https://example.com/a?token=x', 'file:///etc/passwd']:
        with pytest.raises((ValueError, PermissionError)):
            adapters.public_url(url)


def test_lease_and_pagination(catalog):
    store, source, root = catalog
    with store.lease('test'):
        with pytest.raises(RuntimeError):
            with store.lease('test'):
                pass
    for i in range(4):
        (root / f'{i}.txt').write_text('x')
    service.scan(source['id'], store)
    assert store.catalog(category='1', offset=2, limit=2)['total'] == 4
    assert len(store.catalog(category='1', offset=2, limit=2)['items']) == 2


def test_future_schema_is_not_downgraded(tmp_path):
    import sqlite3
    path=tmp_path/'catalog.db'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=2')
    with pytest.raises(RuntimeError):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==2


def test_generated_output_during_scan_is_not_marked_missing(catalog, monkeypatch):
    store, source, root=catalog
    path=root/'output.txt'
    path.write_text('output')
    original=adapters.discover
    def discover(source):
        yield from original(source)
        service.register_output(path, {'task':'concurrent'}, store)
    monkeypatch.setattr(adapters,'discover',discover)
    service.scan(source['id'],store)
    assert store.catalog()['items'][0]['locations'][0]['status']=='available'
