"""Owner UI and separately authenticated worker commands for the HFL bridge."""
from __future__ import annotations

import hmac
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from auth import get_current_user
from config import get_settings
from modules.hfl_corpus import timeline
from modules.hfl_corpus.memory_pins import get_memory_pin_store
from modules.hfl_corpus.corpus import activity_day_entries, corpus_index
from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
from modules.hfl_corpus.secrets import is_secret_entry, normalize_secret_tags
from modules.profile.store import get_profile_store
from modules.hfl_shares.security import verify_csrf_token
from workflows.hfl.agent_bridge_store import AgentBridgeStore, BridgeConflict, digest
from workflows.hfl.timeline_store import FollowUpConflict


POLICY = 'research-draft-v1'
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
    if suffix.endswith('/history'):
        return {'history': store.history(suffix[1:-8])}
    if method == 'GET':
        return {'item': store.get(suffix[1:])}
    actor = payload.pop('_agent_actor')
    return {'item': store.update(suffix[1:], payload, actor=actor)}


def source_snapshot(kind, source_id):
    if kind == 'actionable':
        item = action_call('GET', '/' + source_id)['item']
        if item['status'] in {'done', 'dismissed'}:
            raise BridgeConflict('Closed actionables cannot be executed.')
        source = {key: item.get(key, '') for key in ('id', 'title', 'prompt', 'expected_outcome', 'notes', 'version', 'source')}
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
    runtime = PROMPT_PATH.read_text(encoding='utf-8')
    return {'source_key': f'{kind}:{source_id}', 'kind': kind, 'source_id': source_id,
            'source': source, 'category_guidance': guidance, 'policy': POLICY,
            'runtime_prompt': runtime, 'skill': 'hfl-agent-bridge', 'skill_hash': digest(runtime),
            'instruction_hash': digest({'source': source, 'guidance': guidance, 'runtime': runtime})}


def enqueue(kind, source_id, request_key, actor, auto_complete=False):
    snapshot = source_snapshot(kind, source_id)
    snapshot['auto_complete'] = auto_complete
    snapshot['context'] = evidence_context(snapshot)
    return bridge_store().enqueue(snapshot, request_key, actor)


def evidence_context(snapshot):
    """Bound recall to the linked entry or at most seven recent days / 20 entries."""
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
            selected = [(ref['path'], entry) for entry in (document.entries if document else ()) if timeline.entry_guid(entry) == ref.get('entry_id')]
        else:
            end = min(date.fromisoformat(source['end_date']), datetime.now(ZoneInfo('Asia/Singapore')).date())
            start = max(date.fromisoformat(source['start_date']), end - timedelta(days=6))
            coverage.update(start=start.isoformat(), end=end.isoformat(), truncated=start.isoformat() != source['start_date'])
            documents = () if remote or start > end else corpus_index.documents()
            day = end
            while day >= start and len(selected) < 20:
                rows = remote.day_matches(day, query='', limit=20, include_secrets=False, secret_tags=tags)['matches'] if remote else activity_day_entries(documents, activity_day=day)
                selected.extend((path, entry) for path, entry in rows if not is_secret_entry(entry, tags))
                day -= timedelta(days=1)
            coverage['truncated'] = coverage['truncated'] or len(selected) >= 20
        entries = [{'path': path, 'entry_id': timeline.entry_guid(entry), 'text': entry.text[:2000]} for path, entry in selected[:20] if not is_secret_entry(entry, tags)]
        return {'entries': entries, 'coverage': coverage}
    except (RemoteCorpusError, httpx.HTTPError, KeyError, ValueError):
        return {'entries': [], 'coverage': {'unavailable': True, 'reason': 'Corpus recall could not complete; do not assume there is no evidence.'}}


def sweep():
    store = bridge_store()
    store.expire()
    today = datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
    results, skipped = [], []
    for sub in store.subscriptions():
        if sub['cadence'] == 'off':
            continue
        try:
            snapshot = source_snapshot(sub['kind'], sub['source_id'])
            source = snapshot['source']
            if sub['kind'] == 'pin':
                if sub['cadence'] == 'daily' and not source['start_date'] <= today <= source['end_date']:
                    continue
                if sub['cadence'] == 'after_period' and today <= source['end_date']:
                    continue
            occurrence = source['end_date'] if sub['cadence'] == 'after_period' else today
            snapshot['auto_complete'] = bool(sub['auto_complete'])
            snapshot['context'] = evidence_context(snapshot)
            results.append(store.enqueue(snapshot, f"{sub['source_key']}:{sub['cadence']}:{occurrence}", 'hermes-schedule')['id'])
        except (ValueError, KeyError, httpx.HTTPError):
            skipped.append(sub['source_key'])
    deliver_pending()
    return {'runs': results, 'skipped': skipped}


def apply_action(run, status):
    if run['snapshot']['kind'] != 'actionable':
        return
    source_id = run['snapshot']['source_id']
    actor = f"agent:hermes:{run['id']}:{status}"
    history = action_call('GET', '/' + source_id + '/history')['history']
    existing = next((row for row in history if row['actor'] == actor), None)
    if existing:
        if status == 'in_progress':
            bridge_store().set_version(run['id'], existing['item']['version'])
        return
    version = run['snapshot']['source']['version'] if status == 'in_progress' else run['expected_version']
    payload = {'version': version, 'status': status, '_agent_actor': actor}
    if status == 'done':
        payload['completion_note'] = (run['result']['summary'] + '\n\nAgent run: ' + run['id'])[:3000]
    item = action_call('PATCH', '/' + source_id, payload)['item']
    if status == 'in_progress':
        bridge_store().set_version(run['id'], item['version'])


def accept(run_id, actor):
    store = bridge_store()
    run = store.get(run_id)
    if run['state'] == 'succeeded' and run['applied']:
        return run
    run = store.begin_accept(run_id, actor)
    try:
        if run['result'].get('complete'):
            apply_action(run, 'done')
    except Exception:
        store.acceptance_failed(run_id)
        raise
    store.mark_applied(run_id)
    return store.owner_transition(run_id, 'succeeded', actor, 'Result accepted' + ('; expected outcome completed.' if run['result'].get('complete') else '; further work remains.'))


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
    supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
    if not expected:
        raise HTTPException(503, 'Agent bridge worker token is not configured.')
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, 'Invalid agent bridge token.')
    return 'hermes'


owner_router = APIRouter(prefix='/hfl-corpus/agent-bridge', dependencies=[Depends(owner_auth)])
worker_router = APIRouter(prefix='/api/hfl-agent', dependencies=[Depends(worker_auth)])


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
    if kind not in {'actionable', 'pin'}:
        raise HTTPException(400, 'Unknown source kind.')
    key = f'{kind}:{source_id}'
    store = bridge_store()
    store.expire()
    return {'runs': store.list(key), 'events': store.events(key),
            'subscription': next((sub for sub in store.subscriptions() if sub['source_key'] == key), {'cadence': 'off', 'auto_complete': False})}


@owner_router.post('/sources/{kind}/{source_id}/configure')
def configure(kind: str, source_id: str, payload: dict):
    if payload.get('cadence') != 'off':
        checked(source_snapshot, kind, source_id)
    if kind not in {'actionable', 'pin'}:
        raise HTTPException(400, 'Unknown source kind.')
    checked(bridge_store().subscribe, kind, source_id, payload.get('cadence'), payload.get('auto_complete', False))
    return {'saved': True}


@owner_router.post('/sources/{kind}/{source_id}/run')
def run_now(kind: str, source_id: str, payload: dict, user=Depends(owner_auth)):
    auto = payload.get('auto_complete', False)
    if type(auto) is not bool:
        raise HTTPException(400, 'Invalid completion policy.')
    return checked(enqueue, kind, source_id, payload.get('request_key'), user, auto)


@owner_router.post('/runs/{run_id}/{decision}')
def decide(run_id: str, decision: str, background_tasks: BackgroundTasks, user=Depends(owner_auth)):
    if decision == 'accept':
        run = checked(accept, run_id, user)
    elif decision == 'cancel':
        run = checked(bridge_store().owner_transition, run_id, 'cancelled', user, 'Cancelled by owner; any late agent result will be rejected.')
    else:
        raise HTTPException(400, 'Choose accept or cancel.')
    background_tasks.add_task(deliver_pending)
    return run


@worker_router.get('/queue')
def queue():
    bridge_store().expire()
    return {'runs': [{'id': run['id']} for run in bridge_store().list(state='queued', oldest=True)]}


@worker_router.post('/sweep')
def daily_sweep():
    return sweep()


@worker_router.post('/deliver')
def retry_delivery():
    deliver_pending()
    return {'ok': True}


@worker_router.post('/runs/{run_id}/claim')
def claim(run_id: str, agent=Depends(worker_auth)):
    store = bridge_store()
    run = checked(store.get, run_id)
    if run['state'] != 'queued':
        raise HTTPException(409, 'This request is no longer queued.')
    try:
        current = source_snapshot(run['snapshot']['kind'], run['snapshot']['source_id'])
    except (KeyError, BridgeConflict, ValueError):
        checked(store.owner_transition, run_id, 'cancelled', 'bridge', 'Source is no longer eligible for execution.')
        raise HTTPException(409, 'Source is no longer eligible for execution.') from None
    except httpx.HTTPError:
        raise HTTPException(502, 'The canonical actionable service is unavailable.') from None
    if current['instruction_hash'] != run['snapshot']['instruction_hash']:
        checked(store.owner_transition, run_id, 'cancelled', 'bridge', 'Source changed before execution; request a new run.')
        raise HTTPException(409, 'Instructions changed; request a new run.')
    run = checked(store.claim, run_id, agent)
    try:
        apply_action(run, 'in_progress')
    except (ValueError, KeyError, httpx.HTTPError):
        store.report(run_id, agent, run['lease_token'], 'start-failed', 'failed', {'summary': 'Could not update the actionable. No agent work started.'})
        raise HTTPException(409, 'Could not start the actionable; inspect its current state.') from None
    return store.get(run_id, private=True)


@worker_router.post('/runs/{run_id}/events')
def report(run_id: str, payload: dict, background_tasks: BackgroundTasks, agent=Depends(worker_auth)):
    run = checked(bridge_store().report, run_id, agent, payload.get('lease_token'), payload.get('event_key'), payload.get('kind'), payload.get('payload'))
    if run['state'] == 'review' and run['snapshot']['auto_complete']:
        try:
            run = accept(run_id, 'policy:' + POLICY)
        except (ValueError, KeyError, httpx.HTTPError):
            pass  # Preserve result for owner review if a concurrent edit prevents completion.
    if run['delivery'] == 'pending':
        background_tasks.add_task(deliver_pending)
    return run
