"""Owner UI and separately authenticated worker commands for the HFL bridge."""
from __future__ import annotations

import hmac
import json
import os
import hashlib
import re
import asyncio
from urllib.parse import quote
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from auth import get_current_user
from config import get_settings
from modules.app_settings.store import read_settings
from services.markdown import render_markdown
from modules.hfl_corpus import timeline
from modules.hfl_corpus.memory_pins import get_memory_pin_store
from modules.hfl_corpus.corpus import activity_day_entries, corpus_index
from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
from modules.hfl_corpus.secrets import is_secret_entry, normalize_secret_tags
from modules.profile.store import get_profile_store
from modules.hfl_shares.security import verify_csrf_token
from workflows.hfl.agent_bridge_store import AgentBridgeStore, BridgeConflict, digest, now
from workflows.hfl.timeline_store import FollowUpConflict, priority_key, validate_matrix


POLICY = 'prompt-execution-v3'
PROMPT_PATH = Path(__file__).resolve().parents[3] / 'workflows/hfl/prompts/agent_bridge.md'


def bridge_store():
    configured = os.environ.get('HFL_AGENT_BRIDGE_STORE_PATH')
    return AgentBridgeStore(Path(configured).expanduser() if configured else Path(get_settings().profile_store_path).expanduser().with_name('hfl-agent-bridge.sqlite3'))


def action_call(method, suffix, payload=None):
    settings = get_settings()
    if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.request(method, settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/timeline/items' + suffix,
                                      headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, json=payload)
        if response.status_code == 409:
            raise BridgeConflict('The actionable changed; review it before applying this result.')
        if response.status_code == 404:
            raise KeyError(suffix)
        response.raise_for_status()
        return response.json()
    store = timeline.store()
    if suffix == '' or suffix.startswith('?'):
        items = sorted(store.list(), key=priority_key)
        offset = int(suffix.split('offset=')[-1]) if 'offset=' in suffix else 0
        return {'items': items[offset:offset + 500], 'total': len(items)}
    if suffix.endswith('/history'):
        return {'history': store.history(suffix[1:-8])}
    if method == 'GET':
        return {'item': store.get(suffix[1:])}
    actor = payload.pop('_agent_actor')
    return {'item': store.update(suffix[1:], payload, actor=actor)}


def source_snapshot(kind, source_id):
    if kind == 'mindmap':
        from modules.hfl_corpus.ideas_brainstorm import snapshot
        return snapshot(source_id)
    if kind == 'actionable':
        item = action_call('GET', '/' + source_id)['item']
        if item['status'] in {'done', 'dismissed'}:
            raise BridgeConflict('Closed actionables cannot be executed.')
        source = {key: item.get(key, '') for key in ('id', 'title', 'prompt', 'expected_outcome', 'notes', 'version', 'status', 'source', 'matrix', 'matrix_confidence', 'matrix_reason', 'review_date', 'due_date')}
        source.update({key: item[key] for key in ('description', 'body', 'checklists') if item.get(key)})
        guidance = ''
    elif kind == 'pin':
        pins = get_memory_pin_store().snapshot()
        item = next((pin for pin in pins['ranges'] if str(pin['id']) == source_id), None)
        if not item:
            raise KeyError(source_id)
        category = next((cat for cat in pins['categories'] if cat['id'] == item['category_id']), None)
        if not category:
            raise BridgeConflict('Archived categories cannot be executed.')
        source = dict(item)
        source['category_name'] = category['name']
        guidance = category['instructions']
    else:
        raise ValueError('Choose actionable or pin.')
    if not source.get('prompt', '').strip():
        raise ValueError('Save task instructions before running an agent.')
    try:
        source['attachments'] = input_manifest(kind, source_id)['attachments']
        if kind == 'actionable':
            # Generated outputs are carried by continuation artifacts, not new
            # owner instructions. Attaching them must not invalidate that run.
            with bridge_store().connect() as db:
                generated = {row['run_id'][:8] + '-' + row['name'] for row in db.execute(
                    'SELECT a.run_id,a.name FROM agent_artifacts a JOIN agent_requests r ON r.id=a.run_id WHERE r.source_key=?',
                    ('actionable:' + source_id,))}
            source['attachments'] = [file for file in source['attachments'] if file['name'] not in generated]
    except HTTPException as exc:
        raise ValueError('Supporting files could not be loaded: ' + str(exc.detail)) from None
    runtime = PROMPT_PATH.read_text(encoding='utf-8')
    return {'source_key': f'{kind}:{source_id}', 'kind': kind, 'source_id': source_id,
            'source': source, 'category_guidance': guidance, 'policy': POLICY,
            'execution_settings': action_execution_settings(kind, source_id),
            'runtime_prompt': runtime, 'prompt_path': 'workflows/hfl/prompts/agent_bridge.md', 'prompt_hash': digest(runtime),
            'instruction_hash': digest({'source': {k: v for k, v in source.items() if k not in {'version', 'status', 'updated_at'}}, 'guidance': guidance, 'runtime': runtime})}


def action_execution_settings(kind, source_id):
    if kind == 'actionable':
        from modules.hfl_corpus.action_agents import effective
        return effective(source_id)
    return read_settings()


def enqueue(kind, source_id, request_key, actor, auto_complete=True):
    snapshot = source_snapshot(kind, source_id)
    if kind == 'actionable' and actor == 'hermes-schedule' and snapshot['source']['status'] != 'active':
        raise BridgeConflict('Only Ready actions can be picked up automatically.')
    snapshot['auto_complete'] = False if kind == 'mindmap' else auto_complete
    snapshot['context'] = evidence_context(snapshot)
    store = bridge_store()
    if kind == 'actionable':
        retire_reopened(snapshot)
    run = store.enqueue(snapshot, request_key, actor)
    if run['state'] == 'queued':
        apply_action(run, 'in_progress')
    return store.get(run['id'])


def evidence_context(snapshot):
    """Bound recall to the linked entry or at most seven recent days / 20 entries."""
    if snapshot['kind'] == 'mindmap':
        return {'nodes': snapshot['source']['members'], 'coverage': {'reason': 'Selected permitted map members only.'}}
    tags = normalize_secret_tags(get_profile_store().get().secret_tags)
    remote = RemoteCorpusClient.from_settings() if get_settings().hfl_corpus_api_url else None
    selected = []
    coverage = {'entry_limit': 20, 'day_limit': 7, 'truncated': False}
    source = snapshot['source']
    try:
        if snapshot['kind'] == 'actionable':
            ref = source.get('source') or {}
            if not ref:
                return {'entries': [], 'coverage': {'reason': 'No linked corpus entry.'}}
            document = remote.document(ref['path'], include_secrets=False, secret_tags=tags)[0] if remote else corpus_index.get(ref['path'])
            selected = [(ref['path'], entry) for entry in (document.entries if document else ()) if timeline.entry_evidence_id(entry.text) == ref.get('entry_id')]
        else:
            end = min(date.fromisoformat(source['end_date']), date.fromisoformat(snapshot['occurrence_date']) if snapshot.get('occurrence_date') else datetime.now(ZoneInfo('Asia/Singapore')).date())
            start = max(date.fromisoformat(source['start_date']), end - timedelta(days=6))
            coverage.update(start=start.isoformat(), end=end.isoformat(), truncated=start.isoformat() != source['start_date'])
            documents = () if remote or start > end else corpus_index.documents()
            day = end
            while day >= start and len(selected) < 20:
                rows = remote.day_matches(day, query='', limit=20, include_secrets=False, secret_tags=tags)['matches'] if remote else activity_day_entries(documents, activity_day=day)
                selected.extend((path, entry) for path, entry in rows if not is_secret_entry(entry, tags))
                day -= timedelta(days=1)
            coverage['truncated'] = coverage['truncated'] or len(selected) >= 20
        entries = [{'path': path, 'entry_id': timeline.entry_evidence_id(entry.text), 'text': entry.text[:2000]} for path, entry in selected[:20] if not is_secret_entry(entry, tags)]
        return {'entries': entries, 'coverage': coverage}
    except (RemoteCorpusError, httpx.HTTPError, KeyError, ValueError):
        return {'entries': [], 'coverage': {'unavailable': True, 'reason': 'Corpus recall could not complete; do not assume there is no evidence.'}}


def retire_reopened(snapshot):
    """A new owner revision cannot inherit an old execution's authority."""
    source = snapshot['source']
    if source.get('status') not in {'open', 'active'}:
        return
    store = bridge_store()
    for run in store.list(snapshot['source_key']):
        if run['state'] in {'queued', 'running', 'awaiting_input', 'review'} and source['version'] > (run['expected_version'] or run['snapshot']['source']['version']):
            store.owner_transition(run['id'], 'cancelled', 'bridge', 'Action reopened; this attempt is superseded.')


def older_gap_notice(snapshot, start, end):
    store = bridge_store()
    key = 'older-gap:' + snapshot['source_key'] + ':' + snapshot['source']['start_date']
    if start > end or store.notice_sent(key):
        return
    # An existing run, even a failed run, has already been accounted for in history.
    with store.connect() as db:
        accounted = {row['request_key'] for row in db.execute('SELECT request_key FROM agent_requests WHERE source_key=?', (snapshot['source_key'],))}
    missing = []
    day = start
    while day <= end:
        if f"{snapshot['source_key']}:daily:{day.isoformat()}" not in accounted:
            missing.append(day)
        day += timedelta(days=1)
    if not missing:
        return
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    entry = HflEntry(when=datetime.now(ZoneInfo('Asia/Singapore')),
        moment='Review older missed agent runs: ' + snapshot['source']['title'][:120],
        what_happened=f"{len(missing)} older scheduled occurrences need review, from {missing[0]} through {missing[-1]}. Source: {snapshot['source_key']}. Automatic backfill is limited to the configured recent window. Review the pin and run older work on demand if still useful.",
        why_it_stayed='Makes older scheduling gaps visible without executing stale instructions automatically.',
        tags=('agent-execution', 'follow-up'), source='hfl-agent-execution')
    if os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1':
        store.mark_notice(key)
    elif submit_hfl_entry(entry, source='hfl-agent-execution', dedup_key=key, synthesized=True).get('delivery') in {'persisted', 'forwarded', 'outbox'}:
        store.mark_notice(key)


def sweep():
    store = bridge_store()
    store.expire()
    settings = read_settings()
    instant = datetime.now(ZoneInfo('Asia/Singapore'))
    today = instant.date()
    results, skipped = [], []
    if store.dispatch_due('actions-poll', settings['actions_polling_minutes']):
        try:
            offset = 0
            while True:
                page = action_call('GET', f'?offset={offset}')
                # Collect before mutation: status edits can reorder the canonical list.
                if offset == 0:
                    items = []
                items.extend(page['items'])
                offset += len(page['items'])
                if offset >= page['total'] or not page['items']:
                    break
            for item in sorted(items, key=priority_key):
                if item['status'] == 'active' and item.get('agent_enabled', True) and item.get('prompt', '').strip():
                    try:
                        run = enqueue('actionable', item['id'], f"actionable:{item['id']}:revision:{item['version']}", 'hermes-schedule')
                        results.append(run['id'])
                    except (ValueError, KeyError, httpx.HTTPError):
                        skipped.append('actionable:' + item['id'])
        except httpx.HTTPError:
            skipped.append('actionables:service-unavailable')
    subscriptions = {sub['source_key']: sub for sub in store.subscriptions()}
    for pin in get_memory_pin_store().snapshot()['ranges']:
        key = 'pin:' + str(pin['id'])
        sub = subscriptions.get(key)
        enabled = sub['cadence'] != 'off' if sub else bool(pin.get('agent_enabled'))
        if not enabled or not pin.get('prompt', '').strip():
            continue
        try:
            snap = source_snapshot('pin', str(pin['id']))
            start, end = date.fromisoformat(pin['start_date']), date.fromisoformat(pin['end_date'])
            earliest = today - timedelta(days=settings['pin_backfill_days'])
            if sub and sub['cadence'] == 'after_period':
                days = [end] if today > end else []
                cadence = 'after_period'
            else:
                older_gap_notice(snap, start, min(end, earliest - timedelta(days=1)))
                day = max(start, earliest)
                days = []
                while day <= min(end, today):
                    if day < today or instant.hour >= pin.get('execution_hour', 0):
                        days.append(day)
                    day += timedelta(days=1)
                cadence = 'daily'
            for day in days:
                occurrence = f'{key}:{cadence}:{day.isoformat()}'
                if store.request_exists(occurrence):
                    continue
                snap['auto_complete'] = True
                snap['occurrence_date'] = day.isoformat()
                snap['context'] = evidence_context(snap)
                run = store.enqueue(snap, occurrence, 'hermes-schedule')
                results.append(run['id'])
                break  # One live run per source; the next tick catches up the next occurrence.
        except (ValueError, KeyError, httpx.HTTPError):
            skipped.append(key)
    reconcile_runs()
    deliver_pending()
    return {'runs': list(dict.fromkeys(results)), 'skipped': skipped}


def reconcile_runs():
    store = bridge_store()
    for state in ('queued', 'review', 'accepting', 'failed', 'awaiting_input'):
        for run in store.list(state=state, limit=1000, oldest=True):
            try:
                if state == 'queued':
                    apply_action(run, 'in_progress')
                elif state in {'review', 'accepting'} and run['snapshot'].get('auto_complete'):
                    accept(run['id'], 'policy:' + POLICY)
                elif state in {'failed', 'awaiting_input'} and not run['applied']:
                    apply_action(run, 'incomplete')
                    store.mark_applied(run['id'])
            except (ValueError, KeyError, httpx.HTTPError):
                continue  # Optimistic revisions prevent old attempts from changing a reopened item.


def apply_action(run, status):
    if run['snapshot']['kind'] != 'actionable':
        return
    source_id = run['snapshot']['source_id']
    actor = f"agent:hermes:{run['id']}:{status}"
    history = action_call('GET', '/' + source_id + '/history')['history']
    existing = next((row for row in history if row['actor'] == actor), None)
    if existing:
        if status in {'active', 'in_progress'}:
            bridge_store().set_version(run['id'], existing['item']['version'])
        return
    version = run['expected_version'] or run['snapshot']['source']['version']
    payload = {'version': version, 'status': status, '_agent_actor': actor}
    if status in {'done', 'incomplete'} and run.get('result', {}).get('matrix'):
        payload.update(validate_matrix(run['result']))
    if status == 'done':
        payload['completion_note'] = (run['result']['summary'] + '\n\nAgent run: ' + run['id'])[:3000]
    item = action_call('PATCH', '/' + source_id, payload)['item']
    if status in {'active', 'in_progress'}:
        bridge_store().set_version(run['id'], item['version'])


def accept(run_id, actor):
    store = bridge_store()
    run = store.get(run_id)
    if run['state'] == 'succeeded' and run['applied']:
        return run
    run = store.begin_accept(run_id, actor)
    try:
        apply_action(run, 'done' if run['result'].get('complete') else 'incomplete')
    except Exception:
        store.acceptance_failed(run_id)
        raise
    store.mark_applied(run_id)
    return store.owner_transition(run_id, 'succeeded', actor, 'Result accepted' + ('; prompt completed.' if run['result'].get('complete') else '; further work remains.'))


def deliver_pending():
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import submit_hfl_entry
    store = bridge_store()
    for run in store.list(delivery='pending', limit=50, oldest=True):
        try:
            snap, result = run['snapshot'], run['result']
            if snap['kind'] == 'pin':
                get_memory_pin_store().record_execution_snapshot(run)
            entry = HflEntry(when=datetime.fromisoformat(run['updated_at']), moment='Agent result: ' + snap['source']['title'][:160],
                             what_happened=f"Agent run: {run['id']}\nSource: {run['source_key']}\nExecution state: {run['state']}\nPolicy: {POLICY}\n\n{result.get('summary', '')}",
                             why_it_stayed='Connects delegated intent to an attributed, reviewable result.',
                             tags=('agent-execution', 'follow-up'), references=tuple(result.get('evidence', [])), source='hfl-agent-execution')
            if os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1':
                store.mark_delivery(run['id'], 'preview')
                continue
            delivered = submit_hfl_entry(entry, source='hfl-agent-execution', dedup_key='agent-run:' + run['id'], synthesized=True)
            if delivered.get('delivery') in {'persisted', 'forwarded', 'outbox'}:
                store.mark_delivery(run['id'], 'delivered')
        except Exception:
            # The durable request is the retry source; never lose a result on delivery failure.
            continue


def owner_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, 'Sign in to manage agent work.')
    if request.method != 'GET' and not verify_csrf_token(request.headers.get('X-CSRF-Token', ''), user):
        raise HTTPException(403, 'Invalid form token.')
    return user


def worker_auth(request: Request):
    expected = os.environ.get('HFL_AGENT_BRIDGE_TOKEN', '').strip()
    authorization = request.headers.get('Authorization', '')
    supplied = authorization[7:] if authorization.startswith('Bearer ') else ''
    if not expected:
        raise HTTPException(503, 'Agent bridge worker token is not configured.')
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, 'Invalid agent bridge token.')
    return 'hermes'


owner_router = APIRouter(prefix='/hfl-corpus/agent-bridge', dependencies=[Depends(owner_auth)])
worker_router = APIRouter(prefix='/api/hfl-agent', dependencies=[Depends(worker_auth)])


def remote_inputs(kind):
    return kind in {'actionable', 'idea'} and get_settings().hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1'


def input_remote(method, source_id, attachment_id='', kind='actionable', **kwargs):
    settings = get_settings()
    path = '/api/hfl/actions/' + quote(str(source_id), safe='') + '/attachments'
    if kind == 'idea':
        path = '/api/hfl/timeline/ideas/objects/' + quote(str(source_id), safe='') + '/attachments'
    if attachment_id:
        path += '/' + quote(attachment_id, safe='')
    try:
        with httpx.Client(timeout=120, follow_redirects=False) as client:
            response = client.request(method, settings.hfl_corpus_api_url.rstrip('/') + path,
                                      headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, **kwargs)
    except httpx.HTTPError:
        raise HTTPException(502, 'The canonical attachment service is unavailable.') from None
    if response.is_error:
        raise HTTPException(response.status_code, 'The canonical attachment request failed.')
    return response


def input_manifest(kind, source_id):
    from modules.hfl_corpus.attachments import source_store, require_source
    if remote_inputs(kind):
        return input_remote('GET', source_id, kind=kind).json()
    require_source(kind, source_id)
    store, source = source_store(kind, source_id)
    return {'attachments': store.list(source)}


def input_preview(content, name):
    """Preview passive formats without executing uploaded HTML or SVG."""
    suffix = Path(name).suffix.lower()
    headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
               'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'"}
    media = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp', '.gif':'image/gif',
             '.pdf':'application/pdf', '.mp4':'video/mp4', '.webm':'video/webm', '.mp3':'audio/mpeg', '.wav':'audio/wav', '.ogg':'audio/ogg'}
    if suffix in media:
        return Response(content, media_type=media[suffix], headers=headers)
    if suffix in {'.txt','.csv','.tsv','.json','.log','.md','.markdown'}:
        if len(content) > 2 * 1024 * 1024:
            raise HTTPException(413, 'This document is too large to preview. Download it instead.')
        text = content.decode('utf-8', errors='replace')
        if suffix in {'.md', '.markdown'}:
            return HTMLResponse(str(render_markdown(text)), headers=headers)
        return Response(text, media_type='text/plain', headers=headers)
    if suffix == '.docx':
        from io import BytesIO
        from zipfile import ZipFile, BadZipFile
        from xml.etree import ElementTree
        try:
            with ZipFile(BytesIO(content)) as document:
                info = document.getinfo('word/document.xml')
                if info.file_size > 4 * 1024 * 1024:
                    raise HTTPException(413, 'This document is too large to preview. Download it instead.')
                root = ElementTree.fromstring(document.read(info))
            namespace = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text = '\n\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', namespace))
            return Response(text, media_type='text/plain', headers=headers)
        except (BadZipFile, KeyError, ElementTree.ParseError):
            raise HTTPException(422, 'This document could not be previewed. Download it instead.') from None
    raise HTTPException(415, 'Preview is unavailable for this file type. Download it instead.')


def input_download(kind, source_id, attachment_id, view=False):
    from modules.hfl_corpus.attachments import source_store
    if remote_inputs(kind):
        if view:
            manifest = next((file for file in input_manifest(kind, source_id)['attachments'] if file['id'] == attachment_id), None)
            if not manifest:
                raise HTTPException(404, 'Attachment not found.')
        response = input_remote('GET', source_id, attachment_id, kind=kind)
        if view:
            return input_preview(response.content, manifest['name'])
        return Response(response.content, media_type='application/octet-stream', headers={
            'Content-Disposition': response.headers.get('Content-Disposition', 'attachment'),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    if kind == 'idea':
        from modules.hfl_corpus.attachments import require_source
        require_source(kind, source_id)
    store, source = source_store(kind, source_id)
    manifest = store.get(source, attachment_id)
    if view:
        return input_preview(store.path(manifest).read_bytes(), manifest['name'])
    return FileResponse(store.path(manifest), filename=manifest['name'], media_type='application/octet-stream',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@owner_router.get('/inputs/{kind}/{source_id}')
def owner_inputs(kind: str, source_id: str):
    return grouped_inputs(kind, source_id, input_manifest(kind, source_id))


def grouped_inputs(kind, source_id, result):
    if kind != 'actionable':
        return result
    # Resolve existing files from recorded provenance, never filename guesses.
    from modules.hfl_corpus.action_agents import store as session_store
    origins = {}
    with session_store().connect() as db:
        # Forgotten sessions retain immutable file records. Match both full
        # stored filename and content digest so those outputs stay classified.
        for row in db.execute('SELECT f.session,f.name,f.digest FROM action_agent_files f LEFT JOIN action_agent_sessions s ON s.id=f.session WHERE s.source_id=? OR s.id IS NULL', (source_id,)):
            name = row['session'][:8] + '-' + row['digest'][:8] + '-' + row['name']
            origins[(name, row['digest'])] = row['name']
        for row in db.execute('SELECT a.run_id,a.name,a.digest FROM agent_artifacts a JOIN agent_requests r ON r.id=a.run_id WHERE r.source_key=?', ('actionable:' + source_id,)):
            origins[(row['run_id'][:8] + '-' + row['name'], row['digest'])] = row['name']
    execution_files = {'conversation.md', 'session-transcript.txt', 'repository-changes.zip'}
    files = []
    for file in result['attachments']:
        original = origins.get((file['name'], file.get('digest')))
        group = 'uploaded' if original is None else ('execution' if original in execution_files else 'generated')
        files.append({**file, 'group': group})
    return {**result, 'attachments': files}


@owner_router.post('/inputs/{kind}/{source_id}')
async def owner_upload_inputs(kind: str, source_id: str, files: list[UploadFile] = File(...)):
    from modules.hfl_corpus.attachments import source_store, require_source
    if remote_inputs(kind):
        try:
            response = await asyncio.to_thread(input_remote, 'POST', source_id, kind=kind,
                    files=[('files', (f.filename, f.file, 'application/octet-stream')) for f in files])
            return grouped_inputs(kind, source_id, response.json())
        finally:
            for upload in files:
                await upload.close()
    require_source(kind, source_id)
    store, source = source_store(kind, source_id)
    return grouped_inputs(kind, source_id, {'attachments': await store.upload(source, files)})


@owner_router.get('/inputs/{kind}/{source_id}/{attachment_id}')
def owner_download_input(kind: str, source_id: str, attachment_id: str, view: bool = False):
    return input_download(kind, source_id, attachment_id, view=view)


@owner_router.delete('/inputs/{kind}/{source_id}/{attachment_id}')
def owner_detach_input(kind: str, source_id: str, attachment_id: str):
    from modules.hfl_corpus.attachments import source_store, require_source
    if remote_inputs(kind):
        return grouped_inputs(kind, source_id, input_remote('DELETE', source_id, attachment_id, kind=kind).json())
    require_source(kind, source_id)
    store, source = source_store(kind, source_id)
    store.detach(source, attachment_id)
    return grouped_inputs(kind, source_id, {'attachments': store.list(source)})


@worker_router.get('/runs/{run_id}/inputs/{attachment_id}')
def worker_input(run_id: str, attachment_id: str, request: Request, agent=Depends(worker_auth)):
    run = checked(bridge_store().get, run_id, private=True)
    token = request.headers.get('X-Execution-Lease', '')
    if run['state'] != 'running' or run['agent'] != agent or not token or not hmac.compare_digest(run['lease_token'], token) or run['lease_until'] < now():
        raise HTTPException(409, 'An active execution lease is required.')
    if not any(item['id'] == attachment_id for item in run['snapshot']['source'].get('attachments', [])):
        raise HTTPException(404, 'Attachment is not part of this run.')
    return input_download(run['snapshot']['kind'], run['snapshot']['source_id'], attachment_id)


def artifact_path(run_id, content_hash):
    root = bridge_store().path.parent / 'agent-artifacts'
    root.mkdir(parents=True, exist_ok=True)
    path = root / run_id / content_hash
    if not path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(400, 'Invalid artifact location.')
    return path


@worker_router.post('/runs/{run_id}/artifacts/{name}')
async def upload_artifact(run_id: str, name: str, request: Request, agent=Depends(worker_auth)):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', name):
        raise HTTPException(400, 'Use a simple artifact filename (up to 120 characters).')
    store = bridge_store()
    run = checked(store.get, run_id, private=True)
    token = request.headers.get('X-Execution-Lease', '')
    if run['agent'] != agent or not token or not hmac.compare_digest(run['lease_token'], token) or run['state'] != 'running':
        raise HTTPException(409, 'An active execution lease is required.')
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, 'Artifacts are limited to 20 MB each.')
    content_hash = hashlib.sha256(content).hexdigest()
    path = artifact_path(run_id, content_hash)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        from workflows.hfl.agent_bridge_store import now
        current = db.execute('SELECT state,lease_until FROM agent_requests WHERE id=?', (run_id,)).fetchone()
        if current['state'] != 'running' or current['lease_until'] < now():
            raise HTTPException(409, 'The execution lease expired.')
        previous = db.execute('SELECT digest FROM agent_artifacts WHERE run_id=? AND name=?', (run_id, name)).fetchone()
        if previous and previous['digest'] != content_hash:
            raise HTTPException(409, 'Artifact filenames are immutable within an attempt.')
        if not previous and len(store.artifacts(run_id)) >= 30:
            raise HTTPException(400, 'At most 30 artifacts are allowed per attempt.')
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(content)
            temporary.replace(path)
        db.execute('INSERT OR IGNORE INTO agent_artifacts VALUES (?,?,?,?)', (run_id, name, content_hash, len(content)))
    if run['snapshot']['kind'] == 'actionable':
        from modules.hfl_corpus.action_agents import attach_output
        await attach_output(run['snapshot']['source_id'], run_id[:8] + '-' + name, bytes(content))
    return {'name': name, 'url': f'/hfl-corpus/agent-bridge/artifacts/{run_id}/{quote(name)}'}


@owner_router.get('/artifacts/{run_id}/{name}')
def download_artifact(run_id: str, name: str, view: bool = False):
    artifact = next((item for item in bridge_store().artifacts(run_id) if item['name'] == name), None)
    if not artifact:
        raise HTTPException(404, 'Artifact not found.')
    path = artifact_path(run_id, artifact['digest'])
    if not path.is_file():
        raise HTTPException(404, 'Artifact file is unavailable on this host.')
    headers = {'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store',
               'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox"}
    suffix = Path(name).suffix.lower()
    if view and suffix in {'.md', '.txt', '.csv', '.json', '.py', '.log'} and artifact['size'] <= 1024 * 1024:
        content = path.read_text(encoding='utf-8', errors='replace')
        if suffix != '.md':
            import html
            return HTMLResponse('<pre>' + html.escape(content) + '</pre>', headers=headers)
        return HTMLResponse(str(render_markdown(content)), headers=headers)
    media = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif', '.pdf': 'application/pdf'}
    inline = view and suffix in media
    return FileResponse(path, filename=name, media_type=media.get(suffix, 'application/octet-stream'),
                        content_disposition_type='inline' if inline else 'attachment', headers=headers)


def checked(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except (BridgeConflict, FollowUpConflict) as exc:
        raise HTTPException(409, str(exc)) from None
    except KeyError:
        raise HTTPException(404, 'Source or execution not found.') from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from None
    except httpx.HTTPError:
        raise HTTPException(502, 'The canonical actionable service is unavailable.') from None


@owner_router.get('/sources/{kind}/{source_id}')
def source_view(kind: str, source_id: str):
    if kind not in {'actionable', 'pin', 'mindmap'}:
        raise HTTPException(400, 'Unknown source kind.')
    key = f'{kind}:{source_id}'
    store = bridge_store()
    store.expire()
    runs, events = store.list(key), store.events(key)
    for run in runs:
        run['result']['output_html'] = str(render_markdown(run['result'].get('summary', '')))
    for event in events:
        event['payload']['output_html'] = str(render_markdown(event['payload'].get('summary', '')))
    outcomes, outcomes_error, action_status, has_initial_prompt = [], '', None, None
    if kind == 'actionable':
        try:
            rows = action_call('GET', '/' + source_id + '/history')['history']
            if rows:
                current = max(rows, key=lambda row: row['item']['version'])['item']
                action_status = current['status']
                has_initial_prompt = bool(current.get('prompt', '').strip())
            seen = {run['result'].get('summary', '').strip() for run in runs}
            for row in sorted(rows, key=lambda row: row['item']['version'], reverse=True):
                summary = row['item'].get('completion_note', '').strip()
                if not summary or summary in seen or any('Agent run: ' + run['id'] in summary for run in runs):
                    continue
                seen.add(summary)
                outcomes.append({'summary': summary, 'output_html': str(render_markdown(summary)),
                                 'created_at': row['changed_at'], 'actor': row.get('actor', ''),
                                 'version': row['item']['version']})
        except (KeyError, httpx.HTTPError):
            outcomes_error = 'Saved action outcomes could not be loaded. Retry shortly.'
    return {'runs': runs, 'events': events,
            'outcomes': outcomes, 'outcomes_error': outcomes_error, 'action_status': action_status, 'has_initial_prompt': has_initial_prompt,
            'subscription': next((sub for sub in store.subscriptions() if sub['source_key'] == key), {'cadence': 'daily' if kind == 'actionable' or any(str(p['id']) == source_id and p.get('agent_enabled') for p in get_memory_pin_store().snapshot()['ranges']) else 'off', 'auto_complete': True})}


@owner_router.post('/sources/{kind}/{source_id}/configure')
def configure(kind: str, source_id: str, payload: dict):
    if kind == 'actionable':
        raise HTTPException(400, 'Action discovery is configured in App Settings. Set the action to Ready to request another attempt.')
    if payload.get('cadence') != 'off':
        checked(source_snapshot, kind, source_id)
    if kind not in {'actionable', 'pin'}:
        raise HTTPException(400, 'Unknown source kind.')
    checked(bridge_store().subscribe, kind, source_id, payload.get('cadence'), payload.get('auto_complete', False))
    return {'saved': True}


@owner_router.post('/sources/{kind}/{source_id}/run')
def run_now(kind: str, source_id: str, payload: dict, user=Depends(owner_auth)):
    auto = payload.get('auto_complete', True)
    if type(auto) is not bool:
        raise HTTPException(400, 'Invalid completion policy.')
    return checked(enqueue, kind, source_id, payload.get('request_key'), user, auto)


@owner_router.post('/mindmaps/{identity}/accept-proposal')
def accept_map_proposal(identity: str, payload: dict, user=Depends(owner_auth)):
    import uuid
    from modules.hfl_corpus.ideas_api import save_proposal
    run = checked(bridge_store().get, payload.get('run_id'))
    index = payload.get('index')
    proposals = run['result'].get('ideas', [])
    if run['source_key'] != 'mindmap:' + identity or run['state'] not in {'review', 'succeeded'} or type(index) is not int or not 0 <= index < len(proposals):
        raise HTTPException(409, 'Choose an idea from a reviewable run for this map.')
    raw = {'item': payload.get('item'), 'parents': proposals[index].get('parents', []),
           'request_id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'brainstorm:' + run['id'] + ':' + str(index)))}
    settings = get_settings()
    if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        response = httpx.post(settings.hfl_corpus_api_url.rstrip('/') + '/api/hfl/timeline/ideas/maps/' + identity + '/accept-proposal',
                              json=raw, headers={'Authorization': 'Bearer ' + settings.hfl_corpus_api_token}, timeout=45)
        if response.is_error:
            raise HTTPException(response.status_code, response.json().get('detail', 'Could not save this proposal.'))
        return response.json()
    return save_proposal(identity, raw, user)


@owner_router.post('/runs/{run_id}/{decision}')
def decide(run_id: str, decision: str, background_tasks: BackgroundTasks, payload: dict | None = None, user=Depends(owner_auth)):
    if decision == 'continue':
        return continue_attempt(run_id, payload or {}, user)
    if decision == 'accept':
        run = checked(accept, run_id, user)
    elif decision == 'cancel':
        run = checked(bridge_store().owner_transition, run_id, 'cancelled', user, 'Cancelled by owner; any late agent result will be rejected.')
    else:
        raise HTTPException(400, 'Choose accept, cancel, or continue.')
    background_tasks.add_task(deliver_pending)
    return run


def continue_attempt(run_id: str, payload: dict, user: str):
    store = bridge_store()
    parent = checked(store.get, run_id)
    reply = payload.get('reply', '')
    if not isinstance(reply, str) or len(reply) > 8000:
        raise HTTPException(400, 'Reply must be text of at most 8,000 characters.')
    reply = reply.strip()
    if not reply and parent['state'] == 'awaiting_input' and parent['result'].get('blocked_reason') == 'input':
        raise HTTPException(400, 'Answer the question before continuing.')
    original = parent['snapshot']
    current = checked(source_snapshot, original['kind'], original['source_id'])
    def instructions(source):
        return {k: v for k, v in source.items() if k not in {'version', 'status', 'updated_at'}}
    expected = instructions(original['source'])
    actual = instructions(current['source'])
    # Applying an incomplete result can update priority without changing the task.
    # Accept that exact assessment, but still reject owner edits to instructions
    # or priority that differ from both the snapshot and the agent result.
    if actual != expected and original['kind'] == 'actionable' and parent['result'].get('matrix'):
        expected.update(validate_matrix(parent['result']))
    if actual != expected or current['category_guidance'] != original['category_guidance']:
        raise HTTPException(409, 'The task instructions changed. Start a new run for the edited task.')
    history = list(original.get('continuation', {}).get('history', []))
    history.append({'run_id': run_id, 'result': {k: v for k, v in parent['result'].items() if k != 'output_html'}, 'reply': reply})
    if len(history) > 20 or len(json.dumps(history)) > 1000000:
        raise HTTPException(400, 'Continuation history is full. Summarize the remaining work in a new task.')
    artifacts = {item['name']: item for item in original.get('continuation', {}).get('artifacts', [])}
    artifacts.update({item['name']: {**item, 'run_id': run_id} for item in store.artifacts(run_id)})
    if len(artifacts) > 30:
        raise HTTPException(400, 'Continuation exceeds the 30-file limit.')
    current.update(auto_complete=original.get('auto_complete', True), context=original.get('context', {}),
                   occurrence_date=original.get('occurrence_date'),
                   operation_scope=original.get('operation_scope', parent['request_key']),
                   continuation={'parent_run_id': run_id, 'reply': reply, 'history': history, 'artifacts': list(artifacts.values())})
    run = checked(store.continue_run, run_id, current, payload.get('request_key'), user, reply)
    if run['state'] == 'queued':
        checked(apply_action, run, 'in_progress')
    return store.get(run['id'])


@worker_router.get('/runs/{run_id}/prior-artifacts/{name}')
def prior_artifact(run_id: str, name: str, request: Request, agent=Depends(worker_auth)):
    run = checked(bridge_store().get, run_id, private=True)
    token = request.headers.get('X-Execution-Lease', '')
    if run['state'] != 'running' or run['agent'] != agent or not token or not hmac.compare_digest(run['lease_token'], token) or run['lease_until'] < now():
        raise HTTPException(409, 'An active execution lease is required.')
    artifact = next((item for item in run['snapshot'].get('continuation', {}).get('artifacts', []) if item['name'] == name), None)
    if not artifact:
        raise HTTPException(404, 'Prior artifact not found.')
    path = artifact_path(artifact['run_id'], artifact['digest'])
    if not path.is_file():
        raise HTTPException(404, 'Prior artifact is unavailable.')
    return FileResponse(path, media_type='application/octet-stream', headers={'Cache-Control': 'no-store'})


@worker_router.get('/queue')
def queue():
    bridge_store().expire()
    reconcile_runs()
    return {'runs': [{'id': run['id']} for run in bridge_store().list(state='queued', oldest=True)]}


@worker_router.get('/settings')
def worker_settings():
    return read_settings()


@worker_router.post('/sweep')
def daily_sweep():
    return sweep()


@worker_router.post('/deliver')
def retry_delivery():
    deliver_pending()
    return {'ok': True}


@worker_router.post('/runs/{run_id}/claim')
def claim(run_id: str, payload: dict = None, agent=Depends(worker_auth)):
    store = bridge_store()
    run = checked(store.get, run_id)
    host = run['snapshot'].get('execution_settings', {}).get('agent_host')
    if host and (payload or {}).get('host') != host:
        raise HTTPException(409, 'This request belongs to another worker host.')
    if run['state'] != 'queued':
        raise HTTPException(409, 'This request is no longer queued.')
    try:
        current = source_snapshot(run['snapshot']['kind'], run['snapshot']['source_id'])
    except (KeyError, BridgeConflict, ValueError):
        checked(store.owner_transition, run_id, 'cancelled', 'bridge', 'Source is no longer eligible for execution.')
        raise HTTPException(409, 'Source is no longer eligible for execution.') from None
    except httpx.HTTPError:
        raise HTTPException(502, 'The canonical actionable service is unavailable.') from None
    if current['instruction_hash'] != run['snapshot']['instruction_hash'] or (current['kind'] == 'actionable' and current['source']['version'] != (run['expected_version'] or run['snapshot']['source']['version'])):
        checked(store.owner_transition, run_id, 'cancelled', 'bridge', 'Source changed before execution; request a new run.')
        raise HTTPException(409, 'Instructions changed; request a new run.')
    run = checked(store.claim, run_id, agent, concurrency=read_settings()['agent_concurrency'])
    try:
        apply_action(run, 'in_progress')
    except (ValueError, KeyError, httpx.HTTPError):
        store.report(run_id, agent, run['lease_token'], 'start-failed', 'failed', {'summary': 'Could not update the actionable. No agent work started.'})
        raise HTTPException(409, 'Could not start the actionable; inspect its current state.') from None
    return store.get(run_id, private=True)


@worker_router.post('/runs/{run_id}/events')
def report(run_id: str, payload: dict, background_tasks: BackgroundTasks, agent=Depends(worker_auth)):
    if payload.get('kind') == 'succeeded':
        current = checked(bridge_store().get, run_id)
        if current['snapshot']['kind'] == 'mindmap':
            proposals = (payload.get('payload') or {}).get('ideas')
            members = {n['id'] for n in current['snapshot']['source']['members']}
            if not isinstance(proposals, list) or not 1 <= len(proposals) <= 12:
                raise HTTPException(422, 'Return 1–12 structured brainstorming ideas.')
            from workflows.hfl.ideas_store import content_fields
            for idea in proposals:
                if not isinstance(idea, dict) or not isinstance(idea.get('title'), str) or not idea['title'].strip() or len(idea['title']) > 200:
                    raise HTTPException(422, 'Each proposed idea needs a bounded title.')
                checked(content_fields, idea)
                parents = idea.get('parents', [])
                if not isinstance(parents, list) or len(parents) > 5 or any(not isinstance(p, str) or p not in members for p in parents):
                    raise HTTPException(422, 'Use only supplied map member IDs as parents.')
    run = checked(bridge_store().report, run_id, agent, payload.get('lease_token'), payload.get('event_key'), payload.get('kind'), payload.get('payload'))
    if run['state'] == 'review' and run['snapshot']['auto_complete']:
        try:
            run = accept(run_id, 'policy:' + POLICY)
        except (ValueError, KeyError, httpx.HTTPError):
            pass  # Preserve result for owner review if a concurrent edit prevents completion.
    if run['state'] in {'failed', 'awaiting_input'}:
        try:
            apply_action(run, 'incomplete')
            bridge_store().mark_applied(run_id)
        except (ValueError, KeyError, httpx.HTTPError):
            pass
    if run['delivery'] == 'pending':
        background_tasks.add_task(deliver_pending)
    return run
