from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from apps.file_index import adapters
from apps.file_index.local import configured_sources, browse, select_files
from apps.file_index.service import retrieve_file, register_reference
from apps.file_index.store import Store
from web import page_context, require_user, templates


def owner(request: Request):
    user, redirect = require_user(request)
    if redirect:
        if request.url.path == '/files':
            raise HTTPException(302, headers={'Location': '/login'})
        raise HTTPException(401, 'Sign in to manage files')
    if request.method != 'GET':
        origin = request.headers.get('origin')
        expected = str(request.base_url).rstrip('/')
        if request.headers.get('x-harqis-files') != '1' or (origin and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Same-origin request required')
    return user


router = APIRouter(prefix='/files', dependencies=[Depends(owner)])
guest_router = APIRouter(prefix='/file-share')


def find(table, key):
    try:
        return Store().get(table, key)
    except KeyError:
        raise HTTPException(404, 'Record not found')


def enqueue(operation, **kwargs):
    from celery_client import dispatch
    try:
        task_id = dispatch('workflows.files.tasks.index.' + operation, kwargs, os.environ.get('FILES_QUEUE', 'files'))
    except Exception:
        raise HTTPException(503, 'Worker queue unavailable; retry this operation')
    subject = kwargs.get('source_id') or 'queue'
    if kwargs.get('revision_id'):
        subject = Store().get('revisions', kwargs['revision_id'])['package_id']
    Store().event(subject, 'queued', task_id=task_id, operation=operation, **kwargs)
    return {'task_id': task_id}


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceWrite(Command):
    name: str = Field(min_length=1, max_length=160)
    kind: Literal['local', 'drive', 'http', 'sftp', 'ftp']
    root: str = Field(min_length=1, max_length=2000)
    host: str = Field(default_factory=adapters.host_id, max_length=200)
    profile: str = Field(default='', max_length=120)
    interval_hours: int = Field(default=24, ge=1, le=8760)
    enabled: bool = True
    categories: list[str] = Field(default_factory=list, max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=30)


class FileWrite(Command):
    categories: list[str] = Field(default_factory=list, max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=30)
    entities: list[str] = Field(default_factory=list, max_length=30)


class PackageWrite(Command):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default='', max_length=3000)
    expiry_days: Literal[0, 7, 15, 30] = 7


class RevisionWrite(Command):
    file_ids: list[str] = Field(min_length=1, max_length=500)
    request_id: UUID


class LocationWrite(Command):
    source_id: str
    locator: str = Field(min_length=1, max_length=2000)


class ReferenceWrite(LocationWrite):
    name: str = Field(min_length=1, max_length=250)


@router.get('', response_class=HTMLResponse)
def page(request: Request):
    return templates.TemplateResponse(request, 'modules/files/index.html',
        page_context(request, owner(request), 'files', host_id=adapters.host_id()))


@router.get('/api/sources')
def sources():
    try:
        items = configured_sources()
    except (ValueError, OSError):
        raise HTTPException(503, 'Server folder configuration is unavailable. Check FILES_ALLOWED_ROOTS on the server.')
    return {'items': items, 'automatic_scans': os.environ.get('FILES_ENABLED', '').lower() in {'1', 'true', 'yes'}}


@router.get('/api/indexing-status')
def indexing_progress():
    from apps.file_index.status import indexing_status
    return indexing_status(Store(), sources()['items'])


def local_error(exc):
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(404, 'Folder or file is unavailable. Check that the server drive is connected, then refresh.')
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    return HTTPException(409, 'Cannot read this folder. Check server permissions, then refresh.')


@router.get('/api/sources/{key}/browse')
def browse_source(key: str, path: str = '', offset: int = Query(0, ge=0)):
    source = find('sources', key)
    try:
        return browse(source, path, offset)
    except (ValueError, OSError) as exc:
        raise local_error(exc)


class PickFiles(Command):
    paths: list[str] = Field(min_length=1, max_length=200)


@router.post('/api/sources/{key}/select')
def pick_files(key: str, payload: PickFiles):
    source = find('sources', key)
    try:
        return {'items': select_files(source, payload.paths)}
    except (ValueError, OSError) as exc:
        raise local_error(exc)


@router.post('/api/sources')
def create_source(payload: SourceWrite):
    data = payload.model_dump()
    if data['kind'] == 'drive' and data['root'].startswith('https://drive.google.com/'):
        import re
        match = re.fullmatch(r'/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)/?', urlsplit(data['root']).path)
        if match:
            data['root'] = match.group(1)
    try:
        adapters.validate_source(data)
    except Exception as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, (ValueError, PermissionError)) else 'Source configuration is unavailable')
    source = Store().add('sources', {**data, 'state': 'new', 'last_scan': None})
    Store().event(source['id'], 'source_created')
    return source


@router.put('/api/sources/{key}')
def update_source(key: str, payload: SourceWrite):
    source = find('sources', key)
    data = payload.model_dump()
    if any(source.get(field) != data.get(field) for field in ('kind', 'root', 'host', 'profile')):
        raise HTTPException(422, 'Create a new source to change its storage location')
    return Store().patch('sources', key, data)


@router.post('/api/sources/{key}/scan')
def scan_source(key: str):
    source = find('sources', key)
    if not source.get('enabled', True):
        raise HTTPException(409, 'This location is paused. Resume scans first, or browse and select individual files.')
    if source['kind'] == 'ftp':
        raise HTTPException(422, 'FTP is reference-only; use SFTP for discovery')
    return enqueue('scan_source', source_id=key)


@router.get('/api/catalog')
def catalog(q: str = '', category: str = '', status: str = '', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return Store().catalog(q, category, status, offset, limit)


@router.get('/api/taxonomy')
def taxonomy():
    from config import get_settings
    if get_settings().hfl_corpus_api_url.strip():
        from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
        try:
            return RemoteCorpusClient.from_settings().categories()
        except RemoteCorpusError:
            raise HTTPException(503, 'HFL categories unavailable; check the corpus API connection')
    from modules.hfl_corpus.memory_pins import get_memory_pin_store
    return {'categories': get_memory_pin_store().snapshot()['categories']}


@router.post('/api/references')
def create_reference(payload: ReferenceWrite):
    find('sources', payload.source_id)
    try:
        return register_reference(payload.source_id, payload.locator, payload.name)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(422, str(exc))


@router.get('/api/files/{key}')
def file_detail(key: str):
    return {**find('files', key), 'locations': Store().locations(key), 'history': Store().history(key)}


@router.patch('/api/files/{key}')
def edit_file(key: str, payload: FileWrite):
    find('files', key)
    # Update only the edited metadata, preserving concurrent scan/activity writes.
    import json
    with Store().connect() as db:
        db.execute("UPDATE files SET data=json_set(data,'$.categories',json(?),'$.tags',json(?),'$.entities',json(?)) WHERE id=?",
                   (json.dumps(payload.categories), json.dumps(payload.tags), json.dumps(payload.entities), key))
    Store().event(key, 'metadata_updated')
    return find('files', key)


@router.post('/api/files/{key}/locations')
def add_location(key: str, payload: LocationWrite):
    file = find('files', key)
    find('sources', payload.source_id)
    try:
        register_reference(payload.source_id, payload.locator, file['name'], file_id=key)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(422, str(exc))
    return file_detail(key)


@router.get('/api/files/{key}/download')
def download(key: str, background_tasks: BackgroundTasks):
    find('files', key)
    fd, path = tempfile.mkstemp(prefix='harqis-file-')
    os.close(fd)
    try:
        result = retrieve_file(key, path)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise HTTPException(409, 'File could not be retrieved; inspect its locations and retry')
    background_tasks.add_task(Path(path).unlink, missing_ok=True)
    # Always attachment: downloaded HTML/SVG must not execute on the owner origin.
    return FileResponse(path, filename=result['name'], media_type='application/octet-stream', background=background_tasks,
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/api/files/{key}/opened')
def opened(key: str):
    find('files', key)
    with Store().connect() as db:
        db.execute("UPDATE files SET data=json_set(data,'$.last_opened',?) WHERE id=?", (time.time(), key))
    return {'ok': True}


@router.get('/api/packages')
def packages():
    return {'items': Store().all('packages')}


@router.post('/api/packages')
def create_package(payload: PackageWrite, actor=Depends(owner)):
    return Store().add('packages', {**payload.model_dump(), 'created_at': time.time(), 'actor': actor})


@router.get('/api/packages/{key}')
def package_detail(key: str, before: int = Query(0, ge=0)):
    package = find('packages', key)
    return {**package, 'revisions': sorted([r for r in Store().all('revisions') if r['package_id'] == key], key=lambda r: r['number'], reverse=True),
            'history': Store().history(key, before)}


@router.post('/api/packages/{key}/revisions')
def create_revision(key: str, payload: RevisionWrite, actor=Depends(owner)):
    find('packages', key)
    try:
        return Store().revision(key, payload.file_ids, actor, str(payload.request_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post('/api/revisions/{key}/publish')
def publish_revision(key: str, actor=Depends(owner)):
    revision = find('revisions', key)
    Store().event(revision['package_id'], 'publication_requested', revision=key, actor=actor)
    return enqueue('publish_package', revision_id=key)


@router.get('/api/revisions/{key}/qr')
def revision_qr(key: str, target: Literal['drive', 'page'] = 'drive'):
    from modules.hfl_shares.security import qr_data_uri
    revision = find('revisions', key)
    base = os.environ.get('FILES_PUBLIC_URL', '').rstrip('/')
    if target == 'page' and urlsplit(base).scheme != 'https':
        raise HTTPException(422, 'Configure FILES_PUBLIC_URL with the public HTTPS frontend URL')
    url = revision.get('drive_url') if target == 'drive' else base + '/file-share/' + revision['token']
    if not url:
        raise HTTPException(409, 'Publish this revision first')
    return {'url': url, 'image': qr_data_uri(url)}


@router.get('/api/graph')
def graph(q: str = '', category: str = ''):
    catalog = Store().catalog(q, category, limit=150)
    nodes, edges = {}, []
    profiles = {}
    if any(file.get('entities') for file in catalog['items']):
        from workflows.hfl.entity_store import get_store
        profiles = get_store().profiles()
    for file in catalog['items']:
        key = 'file:' + file['id']
        nodes[key] = {'id': key, 'label': file['name'], 'kind': 'file', 'file_id': file['id']}
        for kind, values in [('category', file.get('categories', [])), ('entity', file.get('entities', []))]:
            for value in values:
                target = kind + ':' + str(value)
                label = profiles.get(str(value), {}).get('name', str(value)) if kind == 'entity' else str(value)
                nodes[target] = {'id': target, 'label': label, 'kind': kind}
                edges.append({'source': key, 'target': target})
    return {'nodes': list(nodes.values()), 'edges': edges, 'total_files': catalog['total'], 'shown_files': len(catalog['items'])}


@guest_router.get('/{token}', response_class=HTMLResponse)
def guest(request: Request, token: str):
    try:
        revision = Store().guest(token)
    except KeyError:
        raise HTTPException(404, 'Package unavailable or expired')
    # Deliberately construct public data: never pass internal paths, entity links,
    # credentials, audit actors, or unpublished revisions into this template.
    public = {key: revision.get(key) for key in ('title', 'description', 'number', 'expires_at', 'drive_url')}
    public['files'] = [{key: copy.get(key) for key in ('name', 'size', 'mime_type', 'url')} for copy in revision['copies'].values()]
    return templates.TemplateResponse(request, 'modules/files/guest.html', {'request': request, 'package': public},
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'})
