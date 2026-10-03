"""Bounded discovery and streaming retrieval. Source credentials stay on the host."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import os
import posixpath
import re
import socket
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx


MAX_BYTES = 2 * 1024 ** 3


def host_id():
    return os.environ.get('FILES_HOST_ID', socket.gethostname()).lower()


def local_path(source, locator=None):
    if source['host'].lower() != host_id():
        raise OSError('Source belongs to another host; use an SFTP source for remote hosts')
    root = Path(source['root']).expanduser().resolve()
    allowed = [Path(p).expanduser().resolve() for p in json.loads(os.environ.get('FILES_ALLOWED_ROOTS', '[]'))]
    if not any(root.is_relative_to(p) for p in allowed):
        raise PermissionError('Source is outside configured FILES_ALLOWED_ROOTS')
    path = Path(locator).resolve() if locator else root
    if not path.is_relative_to(root):
        raise PermissionError('File escapes source root')
    return path


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTP(S) URL without embedded credentials, query, or fragment')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise PermissionError('HTTP sources must resolve to public addresses')
    return parsed


@contextmanager
def http_request(client, method, url):
    """Pin the validated address through connect; preserve TLS SNI and Host."""
    parsed = public_url(url)
    # Validate this resolution too; no later DNS lookup is made by the transport.
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise PermissionError('HTTP source resolved to a non-public address')
    url_object = httpx.URL(url).copy_with(host=addresses[0][4][0])
    request = client.build_request(method, url_object, headers={'Host': parsed.netloc},
                                   extensions={'sni_hostname': parsed.hostname})
    response = client.send(request, stream=True, follow_redirects=False)
    try:
        yield response
    finally:
        response.close()


def sftp_profile(source):
    path = os.environ.get('FILES_SFTP_PROFILES_PATH')
    if not path:
        raise ValueError('Configure FILES_SFTP_PROFILES_PATH')
    profiles = json.loads(Path(path).read_text(encoding='utf-8'))
    profile = profiles[source['profile']]
    root = posixpath.normpath(source['root'])
    allowed = posixpath.normpath(profile['root'])
    if not root.startswith('/') or not (root == allowed or root.startswith(allowed.rstrip('/') + '/')):
        raise PermissionError('SFTP root is outside its configured profile')
    return profile


@contextmanager
def sftp(source):
    import paramiko
    profile = sftp_profile(source)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    if profile.get('known_hosts'):
        client.load_host_keys(profile['known_hosts'])
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(profile['hostname'], port=int(profile.get('port', 22)),
                       username=profile['username'], key_filename=profile.get('key_filename'),
                       password=os.environ.get(profile.get('password_env', '')),
                       timeout=20, auth_timeout=20, banner_timeout=20)
        with client.open_sftp() as remote:
            remote.get_channel().settimeout(60)
            allowed_root = remote.normalize(profile['root'])
            source_root = remote.normalize(source['root'])
            if not (source_root == allowed_root or source_root.startswith(allowed_root.rstrip('/') + '/')):
                raise PermissionError('SFTP source resolves outside the profile root')
            yield remote
    finally:
        client.close()


def remote_path(remote, source, locator):
    root = remote.normalize(source['root'])
    path = remote.normalize(locator)
    if not (path == root or path.startswith(root.rstrip('/') + '/')):
        raise PermissionError('SFTP path escapes source root')
    return path


def drive():
    from apps.apps_config import CONFIG_MANAGER
    from apps.google_apps.references.web.api.drive import ApiServiceGoogleDrive
    return ApiServiceGoogleDrive(CONFIG_MANAGER.get(os.environ.get('FILES_GOOGLE_CONFIG_ID', 'GOOGLE_DRIVE')))


def metadata(name, size=None, modified=None, mime=None, **extra):
    return {'name': name, 'size': size, 'modified': modified,
            'mime_type': mime or mimetypes.guess_type(name)[0] or 'application/octet-stream', **extra}


def validate_source(source):
    kind = source['kind']
    if kind == 'local':
        local_path(source)
    elif kind == 'sftp':
        sftp_profile(source)
    elif kind == 'http':
        public_url(source['root'])
    elif kind == 'drive':
        if not re.fullmatch(r'[A-Za-z0-9_-]+', source['root']):
            raise ValueError('Enter the Drive folder ID, not its URL')
    elif kind != 'ftp':
        raise ValueError('Unsupported source type')


def discover(source):
    kind = source['kind']
    if kind == 'local':
        root = local_path(source)
        if not root.is_dir():
            raise FileNotFoundError('Source directory is missing')
        def warning(path, exc=None):
            # The scan owns this bounded diagnostic buffer; never persist it as source config.
            source['_warning_count'] = source.get('_warning_count', 0) + 1
            warnings = source.setdefault('_warnings', [])
            if len(warnings) < 50:
                warnings.append({'path': str(path), 'error': type(exc).__name__ if exc else 'ExcludedSystemFolder',
                                 'errno': getattr(exc, 'errno', None)})
        def onerror(exc):
            if not exc.filename or Path(exc.filename) == root:
                raise exc
            warning(exc.filename, exc)
        for parent, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            allowed_dirs = []
            for name in dirs:
                path = Path(parent, name)
                if name in {'.Spotlight-V100', '.Trashes', '.fseventsd', '.TemporaryItems'}:
                    warning(path)
                    continue
                try:
                    if not path.is_symlink():
                        allowed_dirs.append(name)
                except OSError as exc:
                    warning(path, exc)
            dirs[:] = allowed_dirs
            for name in files:
                path = Path(parent, name)
                try:
                    if path.is_symlink():
                        continue
                    path = local_path(source, path)
                    info = path.stat()
                    if not stat.S_ISREG(info.st_mode):
                        continue
                except OSError as exc:
                    warning(path, exc)
                    continue
                yield str(path), metadata(name, info.st_size, info.st_mtime_ns)
    elif kind == 'sftp':
        with sftp(source) as remote:
            pending = [remote_path(remote, source, source['root'])]
            while pending:
                folder = pending.pop()
                for item in remote.listdir_iter(folder, read_aheads=10):
                    path = posixpath.join(folder, item.filename)
                    if stat.S_ISDIR(item.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(item.st_mode):
                        yield path, metadata(item.filename, item.st_size, item.st_mtime)
    elif kind == 'http':
        parsed = public_url(source['root'])
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            with http_request(client, 'HEAD', source['root']) as response:
                response.raise_for_status()
                length = response.headers.get('content-length')
                yield source['root'], metadata(posixpath.basename(parsed.path) or parsed.hostname,
                    int(length) if length else None, response.headers.get('last-modified'),
                    response.headers.get('content-type', '').split(';')[0], etag=response.headers.get('etag'))
    elif kind == 'drive':
        service = drive()
        pending, seen = [source['root']], set()
        while pending:
            folder = pending.pop()
            if folder in seen:
                continue
            seen.add(folder)
            for item in service.iter_files(query=f"'{folder}' in parents and trashed = false"):
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    pending.append(item['id'])
                elif item['mimeType'] != 'application/vnd.google-apps.shortcut':
                    yield item['id'], metadata(item['name'], int(item['size']) if item.get('size') else None,
                        item.get('modifiedTime'), item['mimeType'], provider_version=item.get('version'))
    else:
        raise ValueError('FTP is reference-only; choose SFTP for retrieval')


def _copy(source, target, maximum):
    total = 0
    for chunk in iter(lambda: source.read(1024 * 1024), b''):
        total += len(chunk)
        if total > maximum:
            raise ValueError('File exceeds configured transfer limit')
        target.write(chunk)


def retrieve(source, location, destination):
    maximum = int(os.environ.get('FILES_MAX_BYTES', MAX_BYTES))
    kind, locator = source['kind'], location['locator']
    mime = location.get('mime_type') or 'application/octet-stream'
    name = location['name']
    if kind == 'local':
        path = local_path(source, locator)
        before = path.stat()
        with path.open('rb') as reader, open(destination, 'wb') as writer:
            _copy(reader, writer, maximum)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError('File changed during retrieval; retry')
    elif kind == 'sftp':
        with sftp(source) as remote:
            path = remote_path(remote, source, locator)
            before = remote.stat(path)
            with remote.open(path, 'rb') as reader, open(destination, 'wb') as writer:
                _copy(reader, writer, maximum)
            after = remote.stat(path)
            if (before.st_size, before.st_mtime) != (after.st_size, after.st_mtime):
                raise OSError('File changed during retrieval; retry')
    elif kind == 'http':
        public_url(locator)
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            with http_request(client, 'GET', locator) as response, open(destination, 'wb') as writer:
                response.raise_for_status()
                total = 0
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > maximum:
                        raise ValueError('File exceeds configured transfer limit')
                    writer.write(chunk)
    elif kind == 'drive':
        service = drive()
        before = service.get_file(locator, fields='id,name,mimeType,version,size')
        export = 'application/pdf' if before['mimeType'].startswith('application/vnd.google-apps.') else None
        service.download_to_path(locator, destination, maximum=maximum, export_mime=export)
        after = service.get_file(locator, fields='id,version')
        if before.get('version') != after.get('version'):
            raise OSError('Drive file changed during retrieval; retry')
        if export:
            mime, name = export, name + '.pdf'
    else:
        raise ValueError('This source cannot be retrieved')
    digest = hashlib.sha256()
    with open(destination, 'rb') as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'name': name, 'mime_type': mime, 'sha256': digest.hexdigest(), 'size': Path(destination).stat().st_size}
