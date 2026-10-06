"""Private attachment descriptors; recipients only receive opaque reference IDs."""
import hashlib
import json
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

from config import get_settings


def references(identity, manifests=None):
    from modules.hfl_corpus.agent_bridge import input_manifest
    from modules.hfl_corpus.attachments import source_store
    prefix, source_id = identity.split(':', 1)
    kind = {'action': 'actionable', 'idea': 'idea'}.get(prefix)
    if not kind:
        return []
    try:
        if manifests is not None:
            files = manifests
        elif get_settings().hfl_corpus_api_url:
            files = input_manifest(kind, source_id)['attachments']
        else:
            store, source = source_store(kind, source_id)
            files = store.list(source)
    except HTTPException as exc:
        raise ValueError('Object attachments could not load. Retry or disable references.') from exc
    return [(f['name'], json.dumps({'kind': kind, 'source_id': source_id, 'id': f['id'], 'digest': f['digest'],
                                  'service_context': manifests is not None})) for f in files]


def download(reference):
    from modules.hfl_corpus.agent_bridge import input_remote
    from modules.hfl_corpus.attachments import source_store
    value = json.loads(reference.target)
    if value.get('kind') not in {'actionable', 'idea'}:
        raise HTTPException(404, 'Reference unavailable.')
    if get_settings().hfl_corpus_api_url:
        if value.get('service_context'):
            import httpx
            settings = get_settings()
            path = '/api/hfl/timeline/ideas/share-context/attachments/' + '/'.join(
                quote(value[k], safe='') for k in ('kind', 'source_id', 'id'))
            try:
                result = httpx.get(settings.hfl_corpus_api_url.rstrip('/') + path,
                                   headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=120)
                result.raise_for_status()
            except httpx.HTTPError:
                raise HTTPException(404, 'Reference unavailable.') from None
        else:
            result = input_remote('GET', value['source_id'], value['id'], kind=value['kind'])
        if hashlib.sha256(result.content).hexdigest() != value['digest']:
            raise HTTPException(404, 'Reference content changed.')
        return Response(result.content, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(reference.label, safe=''),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    store, source = source_store(value['kind'], value['source_id'])
    manifest = store.get(source, value['id'])
    if manifest['digest'] != value['digest']:
        raise HTTPException(404, 'Reference content changed.')
    return FileResponse(store.path(manifest), filename=reference.label, media_type='application/octet-stream')
