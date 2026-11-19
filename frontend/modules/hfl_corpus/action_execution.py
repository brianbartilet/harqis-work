"""Provider-neutral Action dispatch and receipt-driven Nod reconciliation."""
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from modules.hfl_corpus import agent_bridge as bridge
from modules.hfl_corpus import action_agents
from modules.integrations import nod
from workflows.hfl.action_execution_store import ActionExecutionStore
from workflows.hfl.agent_bridge_store import BridgeConflict, digest, now


TERMINAL = {'succeeded', 'failed', 'cancelled'}


def store():
    return ActionExecutionStore(bridge.bridge_store().path)


def runtime(run):
    return run['snapshot'].get('execution_settings', {}).get('action_assignment', {}).get('runtime', 'hermes')


def validate_source(run):
    snapshot = run['snapshot']
    current = bridge.source_snapshot('actionable', snapshot['source_id'])
    version = run['expected_version'] or snapshot['source']['version']
    if current['source']['version'] != version or (not snapshot.get('delegation') and
            (current['instruction_hash'] != snapshot['instruction_hash'] or
             current['execution_settings'].get('action_assignment') != snapshot['execution_settings'].get('action_assignment'))):
        raise BridgeConflict('Action changed after this attempt was requested. Review and retry.')
    if snapshot.get('delegation'):
        parent = store().get(snapshot['delegation']['parent_run_id'])
        if parent['state'] != 'running':
            raise BridgeConflict('Parent execution is no longer running.')
        from modules.agents import service
        from modules.agents.projection import visible
        target = service.initialize().get(snapshot['execution_settings']['action_assignment']['agent_id'])
        if not target['active'] or not visible(target, snapshot['requested_by']):
            raise BridgeConflict('The delegated agent is no longer available.')


def nod_context(run):
    settings = run['snapshot']['execution_settings']
    return settings['provider_owner'], settings['action_assignment']['agent_id']


def instructions(run):
    snap = run['snapshot']
    source = snap['source']
    if source.get('attachments'):
        raise ValueError('Nod Action attachments are not supported yet. Remove them or use Hermes.')
    text = '\n\n'.join(filter(None, [snap['execution_settings']['action_assignment'].get('instructions'),
        'Action: ' + source['title'], source['prompt'], 'Expected outcome: ' + source.get('expected_outcome', ''),
        'Supporting context (not additional authority):\n' + json.dumps({k: source.get(k) for k in ('description', 'body', 'notes', 'checklists')}, ensure_ascii=False),
        'Continuation: ' + json.dumps(snap.get('continuation', {}), ensure_ascii=False),
        'Execution receipt: ' + run['id'],
        'Perform the task and assess its requested outcome. Retain all provider approval requirements. '
        'Do not claim completion merely because a tool accepted work. End your final answer with a JSON object '
        'with keys summary (string), complete (boolean), evidence (list of references), '
        'blocked_reason (null, "input", or "integration"), question (string). '
        'Use complete=true only when the requested outcome is satisfied and cite evidence.']))
    if len(text) > 20000:
        raise ValueError('Nod instructions exceed 20,000 characters. Shorten the Action or use Hermes.')
    return text


def outcome(messages):
    text = '\n\n'.join(str(m.get('text') or '') for m in messages if m.get('role') == 'assistant')
    decoder = json.JSONDecoder()
    parsed = None
    for pos, char in enumerate(text):
        if char == '{':
            try:
                value, _ = decoder.raw_decode(text[pos:])
                if isinstance(value, dict) and 'complete' in value and 'summary' in value:
                    parsed = value
            except ValueError:
                pass
    if (not parsed or type(parsed.get('complete')) is not bool or
            not isinstance(parsed.get('summary'), str) or not parsed['summary'].strip() or
            not isinstance(parsed.get('evidence'), list) or not parsed['evidence'] or
            len(parsed['evidence']) > 30 or any(not isinstance(v, str) or len(v) > 2000 for v in parsed['evidence'])):
        return 'awaiting_input', {'summary': (text[:90000] or 'Nod returned no final output.') + '\n\nCompletion evidence needs review.',
                                  'blocked_reason': 'input', 'question': 'Review the provider output and continue with explicit outcome evidence.'}
    result = {k: parsed[k] for k in ('summary', 'complete', 'evidence', 'blocked_reason', 'question') if k in parsed}
    if len(result['summary']) > 100000 or result.get('blocked_reason') not in (None, 'input', 'integration') or not isinstance(result.get('question', ''), str) or len(result.get('question', '')) > 8000:
        return 'failed', {'summary': 'Nod returned an invalid outcome. Review its conversation.', 'blocked_reason': 'integration'}
    if result.get('blocked_reason'):
        return 'awaiting_input', result
    return 'succeeded', result


def note(run_id, key, message, kind='progress'):
    dbstore = store()
    with dbstore.connect() as db:
        if not db.execute('SELECT 1 FROM agent_events WHERE run_id=? AND event_key=?', (run_id, key)).fetchone():
            dbstore.event(db, run_id, key, kind, 'platform', {'summary': message})


def fail_queued(run, message):
    dbstore = store()
    with dbstore.connect() as db:
        db.execute("UPDATE agent_requests SET state='failed',result=?,delivery='pending',updated_at=? WHERE id=? AND state='queued'",
                   (json.dumps({'summary': message, 'blocked_reason': 'integration'}), now(), run['id']))
    note(run['id'], 'dispatch-blocked', message)


def submit_nod(run):
    validate_source(run)
    user, identity = nod_context(run)
    view = nod.state(user, identity)
    if not view['active'] or not view['ready'] or view.get('mock'):
        raise ValueError('Nod is inactive, unconfigured, or a demonstration connection.')
    if view['needs_private_input'] or any(t['status'] not in TERMINAL for t in view['turns']):
        note(run['id'], 'provider-busy', 'Queued: the shared Nod conversation is busy or awaiting private input.')
        return
    request = {'thread_id': view['thread_id'], 'binding': view['binding'],
               'request_id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'harqis-action:' + run['id'])), 'text': instructions(run)}
    dbstore = store()
    # Installation identity excludes user: two owners connected to one Nod must serialize.
    if not dbstore.reserve(run['id'], digest(view['url']), request):
        return
    try:
        if dbstore.get(run['id'])['state'] != 'queued':
            dbstore.receipt(run['id'], 'finished')
            return
        validate_source(run)
    except (ValueError, KeyError):
        dbstore.receipt(run['id'], 'finished')
        raise
    try:
        note(run['id'], 'provider-dispatch-plan', 'Submit the frozen Action instructions to the assigned Nod agent, correlate its turn receipt, and assess completion evidence. Provider approval requirements remain in force.', kind='plan')
        receipt = nod.send(user, identity, request)
        dbstore.receipt(run['id'], 'submitted', receipt)
    except Exception:
        # Never blindly resend: even a timeout may mean Nod accepted the message.
        dbstore.receipt(run['id'], 'unknown')
        note(run['id'], 'submission-unknown', 'Nod submission is unresolved. Reconciliation will check the message receipt; no automatic resubmission.')


def reconcile_nod(row):
    dbstore = store()
    run = dbstore.get(row['run_id'], private=True)
    user, identity = nod_context(run)
    view = nod.state(user, identity)
    request, receipt = row['request'], row['receipt']
    if view['thread_id'] != request['thread_id'] or view['binding'] != request['binding']:
        note(run['id'], 'connection-changed', 'Nod conversation or connection changed; receipt correlation needs review. The installation slot remains reserved.')
        return
    if not receipt.get('turnId'):
        message = next((m for m in view['messages'] if m['id'] == request['request_id']), None)
        if not message or not message.get('turnId'):
            note(run['id'], 'receipt-unresolved', 'No matching Nod receipt is visible yet. Do not retry until the provider confirms whether work started.')
            return
        receipt = {'messageId': message['id'], 'threadId': view['thread_id'], 'turnId': message['turnId']}
        dbstore.receipt(run['id'], 'submitted', receipt)
    turn = next((t for t in view['turns'] if t['id'] == receipt['turnId']), None)
    if not turn:
        note(run['id'], 'turn-unavailable', 'The recorded Nod turn is unavailable; unrelated conversation output will not be used.')
        return
    if run['state'] == 'queued':
        run = dbstore.claim(run['id'], 'nod')
        receipt['accepted_at'] = now()
        dbstore.receipt(run['id'], 'submitted', receipt)
        dbstore.report(run['id'], 'nod', run['lease_token'], 'provider-plan', 'plan',
                       {'summary': 'Execute the frozen Action instructions in Nod and evaluate outcome evidence.', 'evidence': ['nod:turn:' + receipt['turnId']]})
        try:
            bridge.apply_action(run, 'in_progress')
        except (ValueError, KeyError):
            note(run['id'], 'status-conflict', 'Action changed while Nod accepted work. Output will be retained without overwriting the owner edit.')
        run = dbstore.get(run['id'], private=True)
    if run['state'] not in {'running', 'awaiting_input'} or (run['state'] == 'awaiting_input' and not receipt.get('provider_wait')):
        if turn['status'] in TERMINAL:
            partial = '\n\n'.join(m.get('text', '') for m in view['messages'] if m.get('turnId') == receipt['turnId'] and m.get('role') == 'assistant')[:16000]
            note(run['id'], 'late-provider-result', 'Tracked Nod turn ended after the local attempt stopped: ' + turn['status'] + '.\n\n' + partial)
            dbstore.receipt(run['id'], 'finished', receipt)
        return
    # A provider receipt, rather than an expiring Hermes worker lease, owns this run.
    with dbstore.connect() as db:
        db.execute('UPDATE agent_requests SET lease_until=? WHERE id=?', ('9999-12-31T00:00:00+00:00', run['id']))
    messages = [m for m in view['messages'] if m.get('turnId') == receipt['turnId']]
    if any((m.get('approval') or {}).get('state') == 'pending' for m in messages) or view['needs_private_input']:
        note(run['id'], 'provider-approval', 'Nod needs approval or private input. Review it in the provider; no approval is granted automatically.')
        if not receipt.get('provider_wait'):
            result = {'summary': 'Nod needs approval or private input. Continue in Nod, then this run will resume automatically.', 'blocked_reason': 'input'}
            receipt['provider_wait'] = True
            if not run['snapshot'].get('delegation'):
                try:
                    bridge.apply_action(run, 'incomplete')
                    current = bridge.action_call('GET', '/' + run['snapshot']['source_id'])['item']
                    if current['status'] == 'incomplete' and current['version'] == (run['expected_version'] or run['snapshot']['source']['version']) + 1:
                        receipt['paused_version'] = current['version']
                except (ValueError, KeyError):
                    pass
            with dbstore.connect() as db:
                db.execute("UPDATE agent_requests SET state='awaiting_input',result=?,applied=1 WHERE id=?", (json.dumps(result), run['id']))
            dbstore.receipt(run['id'], 'submitted', receipt)
        return
    if receipt.pop('provider_wait', False):
        if receipt.get('paused_version') and not run['snapshot'].get('delegation'):
            try:
                current = bridge.action_call('PATCH', '/' + run['snapshot']['source_id'],
                    {'version': receipt['paused_version'], 'status': 'in_progress', '_agent_actor': 'agent:nod:' + run['id'] + ':in_progress'})['item']
                dbstore.set_version(run['id'], current['version'])
            except (ValueError, KeyError):
                pass  # Owner edits win; keep result history without overwriting them.
        with dbstore.connect() as db:
            db.execute("UPDATE agent_requests SET state='running',applied=0 WHERE id=?", (run['id'],))
        dbstore.receipt(run['id'], 'submitted', receipt)
    if turn['status'] not in TERMINAL:
        accepted = datetime.fromisoformat(receipt.get('accepted_at', run['created_at']))
        timeout = run['snapshot']['execution_settings'].get('agent_timeout_seconds', 1200)
        if (datetime.now(timezone.utc) - accepted).total_seconds() > timeout:
            dbstore.report(run['id'], 'nod', run['lease_token'], 'provider-timeout', 'failed',
                {'summary': 'Nod exceeded the execution time limit. Its conversation remains reserved until the tracked turn ends; inspect it before retrying.', 'blocked_reason': 'integration'})
        return
    if turn['status'] == 'succeeded':
        kind, result = outcome(messages)
    else:
        kind, result = 'failed', {'summary': 'Nod execution ' + turn['status'] + '. Review the provider output.', 'blocked_reason': 'integration'}
    dbstore.report(run['id'], 'nod', run['lease_token'], 'provider-result', kind, result)
    dbstore.receipt(run['id'], 'finished', receipt)


def trigger(source_id, request_key, actor):
    return bridge.enqueue('actionable', source_id, request_key, actor)


def validate_ready(source_id, raw):
    item = bridge.action_call('GET', '/' + source_id)['item']
    merged = {**item, **raw}
    if merged.get('status') != 'active' or not merged.get('agent_enabled', True):
        return
    if not str(merged.get('prompt') or '').strip():
        raise HTTPException(422, 'Add an Initial prompt before enabling execution in Ready.')
    try:
        effective = action_agents.effective(source_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if effective.get('action_assignment', {}).get('runtime') == 'nod':
        user, identity = effective['provider_owner'], effective['action_assignment']['agent_id']
        view = nod.state(user, identity)
        if not view['ready'] or not view['active'] or view.get('mock'):
            raise HTTPException(422, 'Nod is not ready for Action execution.')
        if bridge.input_manifest('actionable', source_id)['attachments']:
            raise HTTPException(422, 'Nod Action attachments are not supported yet. Use Hermes or remove the files.')


def children(parent_id):
    with store().connect() as db:
        rows = db.execute("SELECT * FROM agent_requests WHERE json_extract(snapshot,'$.delegation.parent_run_id')=? ORDER BY created_at", (parent_id,)).fetchall()
    return [store().decode(r) for r in rows]


def resolve_submission(run_id, payload, actor):
    """Owner-audited recovery when the provider cannot supply an acceptance receipt."""
    dbstore = store()
    row = next((r for r in dbstore.receipts() if r['run_id'] == run_id), None)
    if not row or row['receipt'].get('turnId'):
        raise ValueError('Only an unresolved submission without a turn receipt can be released.')
    evidence = payload.get('evidence', '')
    if payload.get('confirmed_not_running') is not True or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 2000:
        raise ValueError('Confirm that the provider has no running execution and record how you verified it.')
    run = dbstore.get(run_id)
    user, identity = nod_context(run)
    token = uuid.uuid4().hex
    if not dbstore.lock('action-reconcile', token):
        raise BridgeConflict('Reconciliation is in progress. Retry after it finishes.')
    try:
        row = next((r for r in dbstore.receipts() if r['run_id'] == run_id), None)
        if not row or row['receipt'].get('turnId'):
            raise BridgeConflict('The receipt changed. Refresh before resolving it.')
        view = nod.state(user, identity)
        if any(t['status'] not in TERMINAL for t in view['turns']) or any(m['id'] == row['request']['request_id'] for m in view['messages']):
            raise BridgeConflict('Nod still has active work or the submitted message. Reconcile its receipt instead.')
        note(run_id, 'owner-resolved-submission', actor + ' confirmed no provider execution: ' + evidence)
        fail_queued(run, 'Owner confirmed the unresolved submission did not execute. A new attempt can be requested.')
        dbstore.receipt(run_id, 'finished')
        bridge.reconcile_runs()
        return dbstore.get(run_id)
    finally:
        dbstore.unlock('action-reconcile', token)


def delegation_token(run):
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(bridge.get_settings().secret_key, salt='action-delegation').dumps({'run': run['id'], 'lease': digest(run['lease_token'])})


def delegation_parent(run_id, authorization):
    from itsdangerous import URLSafeTimedSerializer, BadSignature
    try:
        data = URLSafeTimedSerializer(bridge.get_settings().secret_key, salt='action-delegation').loads(authorization.removeprefix('Bearer '), max_age=86400)
        parent = store().get(run_id, private=True)
        if data['run'] != run_id or data['lease'] != digest(parent['lease_token']) or parent['state'] != 'running' or parent['lease_until'] < now():
            raise ValueError()
        if parent['snapshot']['execution_settings'].get('action_assignment', {}).get('mode') != 'butler':
            raise ValueError()
        return parent
    except (BadSignature, ValueError, KeyError):
        raise HTTPException(403, 'Delegation requires the active parent run capability.') from None


def delegate(parent, raw):
    import copy
    from modules.hfl_corpus.action_assignment import validate, resolve
    settings = parent['snapshot']['execution_settings']
    target, prompt, request_key = raw.get('agent_id'), raw.get('prompt'), raw.get('request_key')
    if target not in settings.get('permitted_agent_ids', []) or target == 'butler' or parent['snapshot'].get('delegation'):
        raise ValueError('Choose an explicitly permitted worker; nested delegation is disabled.')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
        raise ValueError('Provide child instructions of 1–16,000 characters.')
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 80:
        raise ValueError('Provide a stable delegation request key of at most 80 characters.')
    dbstore = store()
    key = 'delegate:' + parent['id'] + ':' + request_key
    previous = next((c for c in children(parent['id']) if c['request_key'] == key), None)
    if previous:
        if previous['snapshot']['source']['prompt'] != prompt or previous['snapshot']['execution_settings']['action_assignment']['agent_id'] != target:
            raise BridgeConflict('Delegation request key already used for different work.')
        return previous
    if len(children(parent['id'])) >= 10:
        raise ValueError('This parent has reached its ten-child execution limit.')
    validate_source(parent)
    user = parent['snapshot'].get('requested_by', bridge.get_settings().app_username)
    card = validate({'assignment_mode': 'agent', 'agent_id': target}, {}, user)
    child_settings = resolve(card, bridge.read_settings())
    snapshot = copy.deepcopy(parent['snapshot'])
    snapshot.update(source_key=key, execution_settings=child_settings, auto_complete=True,
                    delegation={'parent_run_id': parent['id'], 'agent_id': target})
    snapshot['source'].update(prompt=prompt, version=parent['expected_version'] or snapshot['source']['version'])
    snapshot['instruction_hash'] = digest({'parent': parent['id'], 'target': target, 'prompt': prompt})
    child = dbstore.enqueue(snapshot, key, 'butler:' + parent['id'])
    note(parent['id'], 'delegated:' + child['id'], 'Delegated to ' + child_settings['action_assignment']['name'] + '; child run ' + child['id'])
    return child


def review_children(parent, payload):
    rows = children(parent['id'])
    if not rows:
        return
    reviewed = payload.get('reviewed_child_ids', [])
    if not isinstance(reviewed, list) or any(not isinstance(v, str) for v in reviewed):
        raise ValueError('reviewed_child_ids must be a list of execution IDs.')
    if set(reviewed) != {r['id'] for r in rows}:
        raise ValueError('Review every delegated result and return reviewed_child_ids before completing the parent.')
    if any(r['state'] in {'queued', 'running', 'review', 'accepting'} for r in rows):
        raise ValueError('Delegated work is still running.')
    if payload.get('complete') and any(r['state'] != 'succeeded' or not r['result'].get('complete') for r in rows):
        raise ValueError('A delegated result is incomplete. Report the parent blocker instead of completing it.')


def tick():
    dbstore = store()
    token = uuid.uuid4().hex
    if not dbstore.lock('action-reconcile', token):
        return {'busy': True}
    warnings, requested = [], []
    try:
        # Reconcile known receipts before dispatch, including cancelled local runs.
        for row in dbstore.receipts():
            try:
                reconcile_nod(row)
            except Exception:
                warnings.append(row['run_id'])
        scheduled = {s['source_id']: s for s in dbstore.schedules()}
        offset = 0
        while True:
            page = bridge.action_call('GET', '?offset=' + str(offset))
            for item in page['items']:
                if item['status'] != 'active' or not item.get('agent_enabled', True):
                    continue
                schedule = scheduled.get(item['id'])
                if schedule and not schedule['enabled']:
                    schedule = None
                if schedule and schedule['next_at'] > now():
                    continue
                key = ('schedule:' + item['id'] + ':' + schedule['next_at']) if schedule else ('actionable:' + item['id'] + ':revision:' + str(item['version']))
                try:
                    prior = {r['id'] for r in dbstore.list('actionable:' + item['id'])}
                    run = trigger(item['id'], key, schedule['actor'] if schedule else 'action-trigger')
                    if run['id'] not in prior:
                        requested.append(run['id'])
                    if schedule:
                        dbstore.advance(item['id'], schedule['next_at'], schedule['minutes'])
                except (ValueError, KeyError, HTTPException):
                    warnings.append(item['id'])
            offset += len(page['items'])
            if offset >= page['total'] or not page['items']:
                break
        for run in dbstore.list(state='queued', oldest=True, limit=1000):
            if runtime(run) == 'nod':
                try:
                    submit_nod(run)
                except (ValueError, KeyError, HTTPException) as exc:
                    fail_queued(run, str(getattr(exc, 'detail', exc)))
        bridge.reconcile_runs()
        return {'warnings': warnings, 'runs': requested}
    finally:
        dbstore.unlock('action-reconcile', token)
