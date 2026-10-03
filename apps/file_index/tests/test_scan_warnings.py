import errno
import json
from pathlib import Path

import pytest

from apps.file_index import adapters, service
from apps.file_index.store import Store


@pytest.mark.parametrize('code', [errno.EPERM, errno.EDEADLK])
def test_inaccessible_child_continues_and_preserves_unvisited(tmp_path, monkeypatch, code):
    root = tmp_path / 'root'
    root.mkdir()
    blocked = root / 'blocked'
    blocked.mkdir()
    (blocked / 'old.txt').write_text('old')
    (root / 'good.txt').write_text('good')
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(root)]))
    monkeypatch.setenv('FILES_HOST_ID', 'test')
    store = Store(tmp_path / 'catalog.db')
    source = store.add('sources', {'name': 'test', 'kind': 'local', 'host': 'test', 'root': str(root), 'enabled': True})
    service.scan(source['id'], store)
    last_success = store.get('sources', source['id'])['last_scan']
    original = adapters.os.scandir

    def scandir(path):
        if Path(path) == blocked:
            raise OSError(code, 'blocked', str(path))
        return original(path)

    monkeypatch.setattr(adapters.os, 'scandir', scandir)
    (root / 'new.txt').write_text('new')
    service.scan(source['id'], store)
    result = store.get('sources', source['id'])
    assert result['state'] == 'partial'
    assert result['processed'] == 2
    assert result['warning_count'] == 1
    assert result['warnings'][0]['path'] == str(blocked)
    assert result['warnings'][0]['errno'] == code
    assert result['last_scan'] == last_success
    assert all(l['status'] == 'available' for f in store.catalog()['items'] for l in f['locations'])
    monkeypatch.setattr(adapters.os, 'scandir', original)
    service.scan(source['id'], store)
    result = store.get('sources', source['id'])
    assert result['state'] == 'ready' and result['warning_count'] == 0
    assert result['processed'] == 3


def test_system_folders_excluded_and_root_failure_still_raises(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    (root / '.Spotlight-V100').mkdir()
    (root / '.Spotlight-V100' / 'index').write_text('system')
    (root / '.user-data').mkdir()
    (root / '.user-data' / 'doc').write_text('keep')
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(root)]))
    monkeypatch.setenv('FILES_HOST_ID', 'test')
    source = {'kind': 'local', 'host': 'test', 'root': str(root)}
    assert [info['name'] for _, info in adapters.discover(source)] == ['doc']
    assert source['_warnings'][0]['error'] == 'ExcludedSystemFolder'
    def fail(path):
        raise PermissionError(errno.EPERM, 'root denied', str(path))
    monkeypatch.setattr(adapters.os, 'scandir', fail)
    with pytest.raises(PermissionError):
        list(adapters.discover(source))
