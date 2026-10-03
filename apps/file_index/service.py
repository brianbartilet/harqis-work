"""Canonical file operations, used by UI, CLI and Celery."""
from __future__ import annotations

import os
import json
import tempfile
import time
from pathlib import Path

from . import adapters
from .store import Store, identity


def error_status(exc):
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    status = status or getattr(getattr(exc, 'resp', None), 'status', None)
    if isinstance(exc, FileNotFoundError) or status == 404:
        return 'missing'
    if isinstance(exc, PermissionError) or status in {401, 403} or type(exc).__name__ == 'RefreshError':
        return 'permission_denied'
    return 'unreachable'


def scan(source_id, store=None):
    store = store or Store()
    source = store.get('sources', source_id)
    if not source.get('enabled', True):
        return {'status': 'disabled'}
    with store.lease('source:' + source_id):
        run_id, count = identity(), 0
        source.update(state='scanning', error=None, started_at=time.time(), _warnings=[], _warning_count=0)
        store.patch('sources', source_id, {'state': 'scanning', 'error': None, 'started_at': source['started_at'], 'finished_at': None, 'warnings': [], 'warning_count': 0, 'processed': 0, 'progress_at': source['started_at']})
        progress_at = time.monotonic()
        store.event(source_id, 'scan_started', run_id=run_id)
        try:
            for locator, info in adapters.discover(source):
                if source['kind'] == 'local' and str(Path(locator).resolve()) in {
                    str(store.path), str(store.path) + '-wal', str(store.path) + '-shm'}:
                    continue
                if count >= int(os.environ.get('FILES_SCAN_LIMIT', '100000')):
                    raise ValueError('Scan limit exceeded; configure smaller source roots or raise FILES_SCAN_LIMIT')
                store.observe(source, locator, info, run_id)
                count += 1
                if count % 100 == 0 or time.monotonic() - progress_at >= 1:
                    store.patch('sources', source_id, {'processed': count, 'progress_at': time.time()})
                    progress_at = time.monotonic()
            with store.connect() as db:
                rows = db.execute('SELECT data FROM locations WHERE source_id=?', (source_id,)).fetchall()
                for row in rows if not source['_warning_count'] else []:
                    location = json.loads(row[0])
                    if (location.get('scan_id') != run_id and
                            (location.get('last_seen') or location['first_seen']) < source['started_at']):
                        location['status'] = 'missing'
                        db.execute('UPDATE locations SET data=? WHERE id=?', (json.dumps(location), location['id']))
            if source['_warning_count']:
                source.update(state='partial', last_attempt=time.time(), error=None, count=count)
            else:
                source.update(state='ready', last_scan=time.time(), error=None, count=count)
            store.event(source_id, 'scan_partial' if source['_warning_count'] else 'scan_completed',
                        run_id=run_id, count=count, warning_count=source['_warning_count'], warnings=source['_warnings'])
        except Exception as exc:
            status = error_status(exc)
            source.update(state=status, error=type(exc).__name__, last_attempt=time.time())
            # A discovery failure does not establish the availability of individual files.
            store.event(source_id, 'scan_failed', run_id=run_id, error=type(exc).__name__, count=count)
            raise
        finally:
            source.update(processed=count, progress_at=time.time(), finished_at=time.time())
            source.update(warning_count=source['_warning_count'], warnings=source['_warnings'])
            store.patch('sources', source_id, {key: source.get(key) for key in
                ('state', 'error', 'started_at', 'last_scan', 'last_attempt', 'count', 'processed', 'progress_at', 'finished_at', 'warning_count', 'warnings')})
    return {'source_id': source_id, 'count': count, 'run_id': run_id}


def retrieve_file(file_id, destination, store=None):
    store = store or Store()
    locations = store.locations(file_id)
    failures = []
    for location in sorted(locations, key=lambda item: item.get('status') != 'available'):
        try:
            source = store.get('sources', location['source_id'])
            result = adapters.retrieve(source, location, destination)
            store.patch('locations', location['id'], {'status': 'available', 'last_downloaded': time.time(),
                'checksum': result['sha256'], 'error': None})
            with store.connect() as db:
                db.execute("UPDATE files SET data=json_set(data,'$.last_downloaded',?) WHERE id=?", (time.time(), file_id))
            store.event(file_id, 'retrieved', location_id=location['id'], sha256=result['sha256'])
            return result
        except Exception as exc:
            store.patch('locations', location['id'], {'status': error_status(exc), 'error': type(exc).__name__})
            failures.append(type(exc).__name__)
    raise OSError('No retrievable location: ' + ', '.join(failures or ['no locations']))


def publish(revision_id, store=None, drive_service=None):
    store = store or Store()
    with store.lease('revision:' + revision_id):
        revision = store.get('revisions', revision_id)
        if revision['state'] in {'published', 'expired'}:
            return {'revision_id': revision_id, 'state': revision['state']}
        service = drive_service or adapters.drive()
        revision.update(state='publishing', error=None)
        store.put('revisions', revision)
        store.event(revision['package_id'], 'publication_started', revision=revision_id)
        try:
            # Package folders are created in My Drive root, not inside a shared parent.
            # Preallocated IDs are persisted before remote creation for crash-safe retries.
            if not revision['folder_id']:
                revision['folder_id'] = service.allocate_id()
                store.put('revisions', revision)
            folder = service.package_object(revision['folder_id'], f"{revision['title']} — revision {revision['number']}")
            revision['drive_url'] = folder.get('webViewLink') or f"https://drive.google.com/drive/folders/{revision['folder_id']}"
            with tempfile.TemporaryDirectory(prefix='harqis-package-') as temporary:
                for index, file in enumerate(revision['files']):
                    copy = revision['copies'].get(file['id'])
                    if copy and copy.get('complete'):
                        continue
                    path = Path(temporary, str(index))
                    if not copy:
                        copy = {'drive_id': service.allocate_id()}
                        revision['copies'][file['id']] = copy
                        store.put('revisions', revision)
                    # If an upload completed but its response was lost, recover its saved
                    # metadata, never describe different bytes as the existing copy.
                    if copy.get('sha256'):
                        from googleapiclient.errors import HttpError
                        try:
                            remote = service.get_file(copy['drive_id'], fields='id,name,size,webViewLink')
                        except HttpError as exc:
                            if exc.resp.status != 404:
                                raise
                        else:
                            copy.update(complete=True, url=remote.get('webViewLink') or f"https://drive.google.com/file/d/{copy['drive_id']}/view")
                            store.put('revisions', revision)
                            continue
                    info = retrieve_file(file['id'], path, store)
                    copy.update(info)
                    store.put('revisions', revision)
                    remote = service.package_object(copy['drive_id'], info['name'], parent_id=revision['folder_id'],
                                                    path=path, mime_type=info['mime_type'])
                    copy.update(complete=True, url=remote.get('webViewLink') or f"https://drive.google.com/file/d/{copy['drive_id']}/view")
                    store.put('revisions', revision)
                    path.unlink()
            # Durable deadline precedes public permission, so a crash cannot leave an
            # untracked, indefinitely public folder. Retries keep the original deadline.
            if not revision.get('publication_started_at'):
                now = time.time()
                revision['publication_started_at'] = now
                revision['expires_at'] = now + revision['expiry_days'] * 86400 if revision['expiry_days'] else None
                store.put('revisions', revision)
            if revision['expires_at'] and revision['expires_at'] <= time.time():
                service.revoke_public_reader(revision['folder_id'])
                revision['state'] = 'expired'
            else:
                revision['permission_id'] = service.public_reader(revision['folder_id'])
                revision.update(state='published', published_at=time.time())
            store.put('revisions', revision)
            store.event(revision['package_id'], revision['state'], revision=revision_id)
        except Exception as exc:
            revision.update(state='failed', error=type(exc).__name__)
            store.put('revisions', revision)
            store.event(revision['package_id'], 'publication_failed', revision=revision_id, error=type(exc).__name__)
            raise
    return {'revision_id': revision_id, 'state': revision['state']}


def expire(store=None, drive_service=None):
    store = store or Store()
    count, failed = 0, 0
    for candidate in store.all('revisions'):
        if not candidate.get('expires_at') or candidate['expires_at'] > time.time() or candidate['state'] == 'expired':
            continue
        try:
            with store.lease('revision:' + candidate['id']):
                revision = store.get('revisions', candidate['id'])
                service = drive_service or adapters.drive()
                service.revoke_public_reader(revision['folder_id'])
                revision.update(state='expired', error=None, revoked_at=time.time())
                store.put('revisions', revision)
                store.event(revision['package_id'], 'expired', revision=revision['id'])
                count += 1
        except Exception as exc:
            failed += 1
            store.event(candidate['package_id'], 'expiry_failed', revision=candidate['id'], error=type(exc).__name__)
    return {'expired': count, 'failed': failed}


def register_output(path, provenance, store=None):
    """Register a generated file only inside an explicitly enabled local source."""
    store = store or Store()
    path = Path(path).resolve()
    for source in store.all('sources'):
        if source['kind'] != 'local' or not source.get('enabled') or source.get('host', '').lower() != adapters.host_id():
            continue
        try:
            resolved = adapters.local_path(source, path)
        except PermissionError:
            continue
        if resolved.is_file():
            info = resolved.stat()
            return store.observe(source, str(resolved), adapters.metadata(resolved.name, info.st_size, info.st_mtime_ns,
                provenance=provenance), 'output-' + identity())
    return None


def register_reference(source_id, locator, name, *, file_id=None, store=None):
    """Register a reference without claiming its content has been observed."""
    import posixpath
    import re
    store = store or Store()
    source = store.get('sources', source_id)
    if source['kind'] == 'local':
        locator = str(adapters.local_path(source, locator))
    elif source['kind'] == 'http':
        if locator != source['root']:
            raise ValueError('HTTP location must match its registered source URL')
        adapters.public_url(locator)
    elif source['kind'] == 'sftp':
        locator, root = posixpath.normpath(locator), posixpath.normpath(source['root'])
        if not locator.startswith(root.rstrip('/') + '/'):
            raise ValueError('Location must be within its SFTP root')
    elif source['kind'] == 'drive':
        if not re.fullmatch(r'[A-Za-z0-9_-]+', locator):
            raise ValueError('Invalid Drive file ID')
    elif source['kind'] == 'ftp':
        from urllib.parse import urlsplit
        parsed = urlsplit(locator)
        if parsed.scheme != 'ftp' or parsed.username or parsed.password or parsed.query:
            raise ValueError('Use an FTP URL without embedded credentials')
    with store.lease('reference:' + source_id):
        with store.connect() as db:
            row = db.execute('SELECT file_id FROM locations WHERE source_id=? AND locator=?', (source_id, locator)).fetchone()
        if row:
            if file_id and row['file_id'] != file_id:
                raise ValueError('Location already belongs to another file')
            return store.get('files', row['file_id'])
        file = store.observe(source, locator, adapters.metadata(name), 'manual', file_id=file_id, observed=False)
        store.event(file['id'], 'reference_registered', source_id=source_id)
        return file
