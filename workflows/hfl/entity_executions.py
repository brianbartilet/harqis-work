"""Bounded executions over the durable consolidation backlog."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import time

from filelock import FileLock

from workflows.hfl import entity_consolidation as runs
from workflows.hfl.entity_store import get_store
from workflows.hfl.entity_run_storage import write_run


def start(run_id, execution_id, max_pairs=40, seconds=900):
    if not execution_id or not 1 <= max_pairs <= 200 or not 30 <= seconds <= 3600:
        raise ValueError('Invalid execution ID or budget')
    with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
        run = runs.load(run_id)
        previous = run.get('executions', {}).get(execution_id)
        if previous:
            if (previous['max_pairs'], previous['seconds']) != (max_pairs, seconds):
                raise ValueError('Execution ID already used with a different budget')
            return previous
        if run['state'] != 'running' or run.get('execution'):
            raise ValueError('Close the active execution before starting another')
        from workflows.hfl.entity_consolidation_work import active_claims
        if active_claims(run):
            raise ValueError('Release existing claims before starting an execution')
        from workflows.hfl.entity_integrity import flagged
        with get_store().connection() as db:
            quarantine = flagged(db)
        eligible = sorted((p for p in run['pairs'].values() if p['state'] == 'pending'
                           and not set(p['ids']).intersection(quarantine)), key=runs.pair_priority)
        # Include the oldest comparison in every bounded selection.
        if eligible:
            oldest = min(eligible, key=lambda p: (p.get('queued_at', 0), p['id']))
            eligible = [oldest] + [p for p in eligible if p['id'] != oldest['id']]
        value = dict(id=execution_id, state='running', created=time.time(), deadline=time.time()+seconds,
                     max_pairs=max_pairs, seconds=seconds, pair_ids=[p['id'] for p in eligible[:max_pairs]],
                     baseline_count=len(run['pairs']), initial_eligible=len(eligible))
        run['execution'] = execution_id
        run.setdefault('executions', {})[execution_id] = value
        runs.save(run)
        return value


def check(run, pair_ids):
    identity = run.get('execution')
    if not identity:
        return
    execution = run['executions'][identity]
    if time.time() >= execution['deadline']:
        raise ValueError('Execution budget reached; close and report this execution')
    if not set(pair_ids).issubset(execution['pair_ids']):
        raise ValueError('Work is outside the bounded execution')


def close(run_id, execution_id, reason, errors=None):
    if reason not in {'budget', 'exhausted', 'provider-failure', 'integrity-concern'}:
        raise ValueError('Choose an explicit stop reason')
    errors = errors or []
    with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
        run = runs.load(run_id)
        execution = run.get('executions', {}).get(execution_id)
        if not execution:
            raise ValueError('Unknown execution')
        if execution['state'] != 'running':
            if execution['stop_reason'] != reason or execution['errors'] != errors:
                raise ValueError('Execution already closed with different results')
            return execution
        from workflows.hfl.entity_integrity import flagged
        with get_store().connection() as db:
            quarantine = flagged(db)
            # Repair receipts after a commit succeeded but saving the run failed.
            receipts = {json.loads(r['result'])['event_id']: json.loads(r['result'])
                        for r in db.execute('SELECT result FROM entity_operations')
                        if json.loads(r['result']).get('action') == 'merged'}
            for row in db.execute("SELECT id,data FROM entity_audit WHERE action='merged'"):
                audit = json.loads(row['data'])
                automatic = audit.get('automatic') or {}
                if automatic.get('run_id') != run_id or automatic.get('execution_id') != execution_id:
                    continue
                receipt = receipts.get(row['id'])
                if not receipt:
                    raise ValueError('Merge audit has no operation receipt; investigate before closing')
                for identity in automatic['pair_ids']:
                    run['pairs'][identity].update(state='merged', operation=receipt,
                        decision=automatic.get('decision') or automatic['group']['decisions'][identity],
                        result_name=audit['name'], related_items=audit['unique_entries'])
                runs.invalidate(run, {member['id'] for member in audit['members']})
        selected = {i: deepcopy(run['pairs'][i]) for i in execution['pair_ids']}
        remaining = [p for p in selected.values() if p['state'] == 'pending']
        if reason == 'exhausted' and remaining:
            raise ValueError('Selected work remains; record the actual stop reason')
        # Receipts, not approved edges, are the report's unit of merged work.
        events = {p['operation']['event_id'] for p in selected.values() if p.get('operation')}
        with get_store().connection() as db:
            operations = [r[0] for r in db.execute('SELECT request_id,result FROM entity_operations')
                          if json.loads(r[1]).get('event_id') in events]
            verified = len(operations) == len(events) and all(db.execute('SELECT 1 FROM entity_audit WHERE id=? AND action=?',
                                     (event, 'merged')).fetchone() for event in events)
        report_id = run_id + '--execution-' + execution_id
        execution.update(state='complete' if reason in {'budget', 'exhausted'} and verified and not errors else 'failed',
                         finished=time.time(), stop_reason=reason, errors=errors, report_id=report_id,
                         operation_ids=sorted(operations), event_ids=sorted(events), verified=verified,
                         remaining_selected=len(remaining),
                         remaining_eligible=sum(p['state'] == 'pending' and not set(p['ids']).intersection(quarantine)
                                                for p in run['pairs'].values()),
                         discovered=max(0, len(run['pairs'])-execution['baseline_count']),
                         integrity_exceptions=quarantine)
        report = dict(id=report_id, state='complete', created=datetime.fromtimestamp(execution['created'], timezone.utc).isoformat(),
                      policy=run['policy'], initial=False, delivery={}, pairs=selected, execution_report=deepcopy(execution))
        for pair in selected.values():
            if pair['state'] != 'pending':
                run['pairs'][pair['id']]['reported_in'] = report_id
        run['claims'] = {}
        run['execution'] = None
        run['checkpoint'] = dict(at=time.time(), counts=runs.view(run, limit=0)['counts'])
        with get_store().connection() as db:
            write_run(db, run)
            write_run(db, report)
        return execution
