"""Configured local locations and bounded, metadata-only file picking."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import adapters
from .store import Store, identity


def configured_sources(store=None):
    """Reconcile configured roots without resetting existing scan preferences."""
    store = store or Store()
    values = json.loads(os.environ.get('FILES_ALLOWED_ROOTS', '[]'))
    if not isinstance(values, list) or any(not isinstance(p, str) or not p.strip() for p in values):
        raise ValueError('FILES_ALLOWED_ROOTS must be a JSON array of folder paths')
    roots = {str(Path(p).expanduser().resolve()) for p in values}
    host = adapters.host_id()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        sources = [json.loads(row[0]) for row in db.execute('SELECT data FROM sources')]
        matched = set()
        for source in sources:
            if source['kind'] != 'local' or source.get('host', '').lower() != host:
                continue
            root = str(Path(source['root']).expanduser().resolve())
            if root in roots:
                matched.add(root)
            if root in roots or source.get('configured_root'):
                source.update(configured_root=True, configured_available=root in roots)
                db.execute('UPDATE sources SET data=? WHERE id=?', (json.dumps(source), source['id']))
        for root in sorted(roots - matched):
            source = {'id': identity(), 'name': Path(root).name or root, 'kind': 'local',
                      'root': root, 'host': host, 'profile': '', 'interval_hours': 24,
                      'enabled': True, 'categories': [], 'tags': [], 'state': 'new',
                      'last_scan': None, 'configured_root': True, 'configured_available': True}
            db.execute('INSERT INTO sources VALUES (?,?)', (source['id'], json.dumps(source)))
    return store.all('sources')


def picker_path(source, relative, store):
    if source['kind'] != 'local':
        raise ValueError('Browse is available for server folders; scan remote locations to see their files')
    root = adapters.local_path(source)
    relative = Path(relative)
    if relative.is_absolute() or relative.drive or '..' in relative.parts:
        raise PermissionError('Choose a file inside this folder')
    candidate = root / relative
    # Do not expose symlink contents, even when their destination is allowlisted.
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink():
            raise PermissionError('Symbolic links are not available in the file picker')
    path = adapters.local_path(source, candidate)
    if str(path) in {str(store.path), str(store.path) + '-wal', str(store.path) + '-shm'}:
        raise PermissionError('The catalog database cannot be selected')
    return path


def browse(source, relative='', offset=0, store=None):
    store = store or Store()
    root = adapters.local_path(source) if source['kind'] == 'local' else None
    directory = picker_path(source, relative, store)
    entries = []
    with os.scandir(directory) as children:
        for index, child in enumerate(children):
            if index >= 10000:
                raise ValueError('This folder has over 10,000 entries. Add a smaller subfolder as a location.')
            if child.is_symlink():
                continue
            try:
                path = picker_path(source, str(Path(child.path).relative_to(root)), store)
            except PermissionError:
                continue
            is_dir = child.is_dir(follow_symlinks=False)
            if not is_dir and not child.is_file(follow_symlinks=False):
                continue
            entries.append({'name': child.name, 'path': path.relative_to(root).as_posix(),
                            'kind': 'folder' if is_dir else 'file',
                            'size': None if is_dir else child.stat(follow_symlinks=False).st_size})
    entries.sort(key=lambda item: (item['kind'] != 'folder', item['name'].casefold(), item['name']))
    current = directory.relative_to(root).as_posix()
    return {'path': '' if current == '.' else current, 'items': entries[offset:offset + 100],
            'total': len(entries), 'offset': offset}


def select_files(source, paths, store=None):
    store = store or Store()
    files = []
    # Validate the whole selection before recording any metadata.
    for relative in dict.fromkeys(paths):
        path = picker_path(source, relative, store)
        if not path.is_file():
            raise FileNotFoundError('A selected file is no longer available. Refresh the folder and try again.')
        info = path.stat()
        files.append((path, adapters.metadata(path.name, info.st_size, info.st_mtime_ns)))
    return [store.observe(source, str(path), metadata, 'picker-' + identity()) for path, metadata in files]
