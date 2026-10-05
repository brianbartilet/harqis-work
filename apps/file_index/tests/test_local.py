import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.file_index.local import browse, configured_sources, select_files
from apps.file_index.store import Store


@pytest.fixture
def local_catalog(tmp_path, monkeypatch):
    root = tmp_path / 'Documents'
    root.mkdir()
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(root), str(root / '.')]))
    monkeypatch.setenv('FILES_HOST_ID', 'test-host')
    store = Store(tmp_path / 'catalog.db')
    return store, root


def test_configured_roots_reconcile_concurrently_and_preserve_preferences(local_catalog, monkeypatch):
    store, root = local_catalog
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: configured_sources(store), range(8)))
    source, = store.all('sources')
    assert source['root'] == str(root)
    store.patch('sources', source['id'], {'enabled': False, 'name': 'My documents', 'tags': ['keep'], 'interval_hours': 48})
    same, = configured_sources(store)
    assert (same['id'], same['enabled'], same['name'], same['tags'], same['interval_hours']) == (source['id'], False, 'My documents', ['keep'], 48)
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', '[]')
    removed, = configured_sources(store)
    assert removed['configured_available'] is False
    with pytest.raises(PermissionError):
        browse(removed, store=store)
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(root)]))
    restored, = configured_sources(store)
    assert restored['configured_available'] is True
    assert restored['enabled'] is False


def test_existing_local_source_is_adopted_without_duplicate(local_catalog):
    store, root = local_catalog
    original = store.add('sources', {'name': 'Existing', 'kind': 'local', 'root': str(root), 'host': 'TEST-HOST', 'enabled': False})
    source, = configured_sources(store)
    assert source['id'] == original['id']
    assert source['enabled'] is False


def test_picker_browses_and_registers_real_files_without_scanning(local_catalog):
    store, root = local_catalog
    folder = root / 'Reports'
    folder.mkdir()
    (folder / 'brief.txt').write_text('hello')
    source, = configured_sources(store)
    listing = browse(source, store=store)
    assert listing['items'] == [{'name': 'Reports', 'path': 'Reports', 'kind': 'folder', 'size': None}]
    assert store.catalog()['total'] == 0
    assert browse(source, 'Reports', store=store)['items'][0]['name'] == 'brief.txt'
    file, = select_files(source, ['Reports/brief.txt'], store)
    again, = select_files(source, ['Reports/brief.txt', 'Reports/brief.txt'], store)
    assert file['id'] == again['id']
    assert store.catalog()['total'] == 1
    assert store.locations(file['id'])[0]['status'] == 'available'
    assert (folder / 'brief.txt').read_text() == 'hello'


def test_picker_rejects_escape_and_missing_batch_without_partial_additions(local_catalog):
    store, root = local_catalog
    (root / 'good.txt').write_text('hello')
    source, = configured_sources(store)
    for path in ['../', str(root.parent)]:
        with pytest.raises(PermissionError):
            browse(source, path, store=store)
    with pytest.raises(FileNotFoundError):
        select_files(source, ['good.txt', 'missing.txt'], store)
    assert store.catalog()['total'] == 0
    with pytest.raises(FileNotFoundError):
        select_files(source, ['.'], store)


def test_picker_omits_catalog_and_paginates(local_catalog):
    _, root = local_catalog
    store = Store(root / 'catalog.db')
    source, = configured_sources(store)
    for index in range(105):
        (root / f'{index:03}.txt').write_text('x')
    first = browse(source, store=store)
    second = browse(source, offset=100, store=store)
    assert first['total'] == 105
    assert len(first['items']) == 100 and len(second['items']) == 5
    with pytest.raises(PermissionError):
        select_files(source, ['catalog.db'], store)


def test_picker_does_not_follow_symlinks(local_catalog, tmp_path):
    store, root = local_catalog
    outside = tmp_path / 'private.txt'
    outside.write_text('private')
    link = root / 'link.txt'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('Creating symlinks requires OS permission')
    source, = configured_sources(store)
    assert browse(source, store=store)['items'] == []
    with pytest.raises(PermissionError):
        select_files(source, ['link.txt'], store)
