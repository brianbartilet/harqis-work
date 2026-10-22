"""Resolve entry mentions to established identities without growing merge trees."""
import json
import logging
import os
import re
import time
from copy import deepcopy
from datetime import datetime, timezone

from workflows.hfl.entity_store import digest, get_store
from workflows.hfl import entity_matching as matching, entity_merges, entity_soul

TASK = 'workflows.knowledge.tasks.connected_hfl.resolve_corpus_entities'
POLICY = 'entity-resolution-v1'
CACHE_POLICY = 'immediate-comparison-v1'  # Bump when the evaluator prompt/contract changes.


def evaluate_cached(store, pairs):
    """Persist completed comparisons even if a later batch or commit must retry."""
    model = os.environ.get('HARQIS_ENTITY_MATCH_MODEL', os.environ.get(
        'HARQIS_CONNECTED_ANSWER_MODEL', 'claude-haiku-4-5-20251001'))
    signatures = {p['id']: digest([p, model, POLICY, CACHE_POLICY]) for p in pairs}
    found, missing = {}, []
    with store.connection() as db:
        for pair in pairs:
            row = db.execute('SELECT * FROM entity_resolution_cache WHERE id=?', (pair['id'],)).fetchone()
            if row and row['signature'] == signatures[pair['id']]:
                found[pair['id']] = (json.loads(row['data']), row['model'])
            else:
                missing.append(pair)
        db.execute("""INSERT INTO state VALUES ('resolution-cache-hits',?) ON CONFLICT(key)
            DO UPDATE SET value=CAST(CAST(value AS INTEGER)+? AS TEXT)""", (str(len(found)), len(found)))
    for offset in range(0, len(missing), 8):
        chunk = missing[offset:offset + 8]
        evaluated, used_model = matching.evaluate(chunk, immediate=True)
        decisions = {d.get('id'): d for d in evaluated if isinstance(d, dict)}
        if set(decisions) != {p['id'] for p in chunk} or len(evaluated) != len(chunk):
            raise ValueError('Resolver omitted candidates; retry pending work')
        with store.connection() as db:
            for pair in chunk:
                decision = decisions[pair['id']]
                db.execute('INSERT OR REPLACE INTO entity_resolution_cache VALUES (?,?,?,?,?)',
                           (pair['id'], signatures[pair['id']], json.dumps(decision), used_model, time.time()))
                found[pair['id']] = (decision, used_model)
            db.execute("""INSERT INTO state VALUES ('resolution-comparisons',?) ON CONFLICT(key)
                DO UPDATE SET value=CAST(CAST(value AS INTEGER)+? AS TEXT)""", (str(len(chunk)), len(chunk)))
    return found


def dispatch_pending():
    """Reserve one wakeup under the worker lock; expired reservations recover via the sweeper."""
    if not os.environ.get('HARQIS_ENTITIES_DB') or not matching.enabled():
        return {'state': 'disabled'}
    import math
    from uuid import uuid4
    from filelock import FileLock, Timeout
    from core.apps.sprout.app.celery import SPROUT
    store = get_store()
    lock = FileLock(str(store.path) + '.resolution.lock', timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return {'state': 'coalesced'}
    try:
        now = time.time()
        with store.connection() as db:
            due = db.execute("SELECT min(next_attempt) FROM entity_resolution_jobs WHERE state='pending'").fetchone()[0]
        if due is None:
            return {'state': 'idle'}
        reservation = store.state('resolution-wakeup') or {}
        # New ready work may replace a future wakeup. Its old token becomes inert.
        cooldown = store.state('resolution-task-error') or {}
        scheduled_at = max(now + 2, due, cooldown.get('retry_at', 0))
        if reservation.get('expires_at', 0) > now and reservation.get('scheduled_at', 0) <= scheduled_at:
            return {'state': 'coalesced'}
        token = uuid4().hex
        store.state('resolution-wakeup', dict(token=token, scheduled_at=scheduled_at,
                                             expires_at=scheduled_at + 600))
        try:
            SPROUT.send_task(TASK, kwargs={'dispatch_id': token}, task_id=token,
                            queue=os.environ.get('HARQIS_ENTITIES_QUEUE', 'hfl'),
                            countdown=max(2, math.ceil(scheduled_at - now)))
            store.state('resolution-last-dispatch', now)
            return {'state': 'queued', 'task_id': token}
        except Exception as exc:
            # Broker acknowledgement may have been lost. An expired reservation
            # can be replaced; only its current token is allowed to process work.
            logging.getLogger(__name__).warning('Entity resolution dispatch failed: %s', type(exc).__name__)
            store.state('resolution-dispatch-error', dict(at=now, error=type(exc).__name__))
            return {'state': 'dispatch-uncertain'}
    finally:
        lock.release()


def target_signature(entity, soul):
    return digest([entity['id'], entity['kind'], entity.get('profile'), soul])


def rule_matches(rule, entry, mention, target):
    if not rule['enabled'] or entry['source'] not in rule['sources']:
        return False
    if matching.normalize(rule['observed_name']) != matching.normalize(mention['label']):
        return False
    body = entry['text'].casefold()
    if not all(v.casefold() in body for v in rule['required_context']):
        return False
    if any(v.casefold() in body for v in rule['excluded_context']):
        return False
    # A literal first name inside a different full name is not this confirmed alias.
    if mention['kind'] == 'people' and len(mention['label'].split()) == 1:
        names = [target['label'], *(target.get('profile') or {}).get('aliases', [])]
        full = re.findall(r'\b' + re.escape(mention['label']) + r'\s+[A-Z][a-z]+\b', entry['text'])
        if any(matching.normalize(n) not in {matching.normalize(x) for x in names} for n in full):
            return False
    return True


def assignments(entries, profiles, souls, db):
    """Projection only uses assignments supported by current source and target state."""
    result = {}
    rows = {e['id']: e for e in entries}
    aliases = {r['alias']: r['canonical'] for r in db.execute('SELECT alias,canonical FROM decisions WHERE active=1')}
    inactive = {r['id'] for r in db.execute('SELECT id FROM entity_merges WHERE active=0')}
    from modules.hfl_corpus.entities import entry_hash
    hashes = {identity: entry_hash(entry) for identity, entry in rows.items()}
    signatures = {}
    for row in db.execute('SELECT * FROM entity_resolutions'):
        data = json.loads(row['data'])
        entry = rows.get(row['entry_id'])
        target = row['target_id']
        # Merges/splits require reassessment; never silently transplant an approval.
        if not entry or target not in profiles or target in aliases or target in inactive:
            continue
        entity = dict(id=target, kind=profiles[target]['kind'], profile=profiles[target])
        if target not in signatures:
            signatures[target] = target_signature(entity, souls.get(target, entity_soul.empty()))
        evidence_valid = all(hashes.get(i) == h
                             for i, h in data.get('evidence_hashes', {}).items())
        if (data.get('active') and data.get('policy') == POLICY and data['hash'] == hashes[entry['id']]
                and evidence_valid
                and data['target_signature'] == signatures[target]
                and not matching.blocked(db, [row['mention_id'], target])):
            result[(row['entry_id'], row['mention_id'])] = {**data, 'target_id': target}
    return result


def process_batch(use_model=True, entry_id=None):
    if not matching.enabled():
        return {'state': 'disabled', 'processed': 0, 'pending': 0}
    from modules.hfl_corpus import entities
    from workflows.hfl.entity_candidates import CandidateIndex, incoming_candidates, similarity
    from workflows.hfl.entity_consolidation import corroborated, evidence
    from workflows.hfl.entity_resolution_scope import Scope
    store = get_store()
    with store.connection() as db:
        db.execute('BEGIN')
        jobs = list(db.execute("""SELECT * FROM entity_resolution_jobs
            WHERE state='pending' AND next_attempt<=? AND (? IS NULL OR entry_id=?)
            ORDER BY created_at,entry_id LIMIT 8""", (time.time(), entry_id, entry_id)))
        if not jobs:
            return {'processed': 0, 'pending': 0}
        observed_scope = Scope(db)
    signatures = {j['entry_id']: observed_scope.signature(j['entry_id']) for j in jobs}
    entries = {e['id']: deepcopy(e) for e in entities.current_entries()}
    records = store.records()
    current = entities.entity_index(resolve_mentions=False)
    relevant_ids = {i for j in jobs for i in observed_scope.identities(j['entry_id'])}
    evidence_ids = {e for j in jobs for e in observed_scope.evidence_ids(j['entry_id'])}
    evidence_ids.update(e['id'] for target in current if target['id'] in relevant_ids for e in target['entries'])
    labels = {e['id']: e['label'] for e in current}
    # Only established profiles are targets. A raw mention is never its own anchor.
    targets = [e for e in current if e.get('profile')]
    target_ids = {e['id'] for e in targets}
    candidate_index = CandidateIndex(targets)
    souls = entity_soul.all_souls()
    with store.connection() as db:
        already_resolved = assignments(list(entries.values()), store.profiles(), souls, db)
        from workflows.hfl.entity_integrity import flagged
        quarantine = flagged(db)
    plans, model_pairs, pair_plans = [], [], {}
    for job in jobs:
        entry = entries.get(job['entry_id'])
        record = records.get(job['entry_id'], {})
        if (not entry or entry['source'] in {'entities-audit', 'entity-consolidation'}
                or record.get('hash') != entities.entry_hash(entry)):
            continue
        for mention in record.get('mentions', []):
            if (entry['id'], mention['id']) in already_resolved:
                continue
            canonical = store.resolve(mention['id'])
            if canonical in quarantine:
                plans.append(dict(entry=entry, mention=mention, matches=[], pairs=[], suspect=[canonical]))
                continue
            if store.resolve(mention['id']) != mention['id'] or mention['id'] in target_ids:
                continue
            new = {**mention, 'entries': [dict(id=entry['id'], evidence=entry['text'][:16000],
                   source=entry['source'], date=entry['date'], title=entry['title'])]}
            pool = [e for e in targets if e['kind'] == mention['kind'] and e['id'] != mention['id']]
            suspect = {t['id'] for t in incoming_candidates(new, candidate_index) if t['id'] in quarantine}
            suspect.update(t['id'] for t in pool if t['id'] in quarantine and any(
                rule_matches(rule, entry, mention, t)
                for rule in souls.get(t['id'], entity_soul.empty())['identity_rules']))
            suspect = sorted(suspect)
            plan = dict(entry=entry, mention=mention, matches=[], pairs=[], suspect=suspect)
            with store.connection() as db:
                pool = [e for e in pool if not matching.blocked(db, [mention['id'], e['id']])]
            # Explicit exclusions remain vetoes even if the model would suggest a match.
            pool = [t for t in pool if not any(
                matching.normalize(r['observed_name']) == matching.normalize(mention['label'])
                and entry['source'] in r['sources'] and r['enabled']
                and any(v.casefold() in entry['text'].casefold() for v in r['excluded_context'])
                for r in souls.get(t['id'], {}).get('identity_rules', []))]
            for target in pool:
                soul = souls.get(target['id'], entity_soul.empty())
                rules = [r for r in soul['identity_rules'] if rule_matches(r, entry, mention, target)]
                if rules:
                    plan['matches'].append((target, dict(method='confirmed-rule', rule_id=rules[0]['id'],
                                                         reason='Confirmed alias within its explicit source and context scope')))
            if not plan['matches'] and use_model and pool:
                permitted = {t['id'] for t in pool}
                shortlist = [t for t in incoming_candidates(new, candidate_index) if t['id'] in permitted]
                for target in shortlist:
                    # Assess with source excerpts; soul prose is not corroborating evidence.
                    pair_id = digest([entry['id'], mention['id'], target['id']])
                    pair = dict(id=pair_id, left=evidence(new), right=evidence(target), signals=similarity(new, target))
                    soul = souls.get(target['id'], entity_soul.empty())
                    pair['right']['soul_context'] = dict(markdown=soul['markdown'][:4000],
                        relationships=[dict(relation=r['relation'], target_name=labels.get(store.resolve(r['target_id']), 'Unavailable'),
                                            since=r.get('since'), until=r.get('until')) for r in soul['relationships'][:12]],
                        journal=[r['text'][:1000] for r in soul['journal'][-4:]])
                    model_pairs.append(pair)
                    pair_plans[pair_id] = (plan, target, pair)
                    plan['pairs'].append(pair_id)
            plans.append(plan)
    # Check snapshot assembly before paying for any comparisons.
    with store.connection() as db:
        db.execute('BEGIN')
        assembled = Scope(db)
        if any(assembled.signature(i) != signature for i, signature in signatures.items()):
            raise ValueError('Entity state changed; resolution will retry with current context')
    # Reuse only identical model inputs; corroboration and commit vetoes still run.
    decisions = {}
    evaluated_pairs = evaluate_cached(store, model_pairs)
    for offset in range(0, len(model_pairs), 8):
        chunk = model_pairs[offset:offset + 8]
        found = {p['id']: evaluated_pairs[p['id']][0] for p in chunk}
        decisions.update(found)
        for pair in chunk:
            plan, target, original = pair_plans[pair['id']]
            decision = found[pair['id']]
            model = evaluated_pairs[pair['id']][1]
            if corroborated(decision, original):
                supporting_ids = sorted({a['id'] for a in original['right']['activity']
                    if any(f.get('right_quote') and f['right_quote'] in a['text']
                           and (not f.get('right_entry_id') or f['right_entry_id'] == a['id'])
                           for f in decision.get('facts', []) if isinstance(f, dict))})
                plan['matches'].append((target, dict(method='contextual', reason=decision['reason'],
                                                    decision=decision, model=model, evidence_entry_ids=supporting_ids)))
    # Re-read all relevant source permissions/content, including competing evidence.
    latest = {e['id']: e for e in entities.current_entries()}
    def content_signature(entry):
        return digest([entities.entry_hash(entry), entry.get('title'), entry.get('origin_id')]) if entry else None
    changed_entries = {i for i in entries.keys() | latest.keys()
                       if content_signature(entries.get(i)) != content_signature(latest.get(i))}
    # Explicit repository references can appear before enrichment creates a row.
    for identity in changed_entries - evidence_ids:
        if any(observed_scope.resolve(m['id']) in relevant_ids
               for entry in (entries.get(identity), latest.get(identity)) if entry
               for m in entities.explicit_mentions(entry)):
            evidence_ids.add(identity)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current_scope = Scope(db)
        if any(current_scope.signature(i) != signature for i, signature in signatures.items()):
            raise ValueError('Entity state changed; resolution will retry with current context')
        if changed_entries.intersection(evidence_ids):
            raise ValueError('Entity evidence changed; resolution will retry with current context')
        for plan in plans:
            entry, mention = plan['entry'], plan['mention']
            if entry['id'] not in latest or entities.entry_hash(latest[entry['id']]) != entities.entry_hash(entry):
                continue
            uncertain = bool(plan['matches']) or any(decisions[p].get('decision') != 'separate' for p in plan['pairs'])
            outcome = 'integrity-review' if plan['suspect'] else ('ambiguous' if uncertain else 'no-candidate')
            outcome_data = dict(candidate_ids=sorted({t['id'] for t, _ in plan['matches']} |
                                                     {pair_plans[p][1]['id'] for p in plan['pairs']} |
                                                     set(plan['suspect'])),
                                next_step='Reconsider when source evidence or candidate identities change')
            evidence_version = digest([entities.entry_hash(entry), signatures[entry['id']], POLICY])
            db.execute('INSERT OR REPLACE INTO entity_resolution_outcomes VALUES (?,?,?,?,?,?)',
                       (entry['id'], mention['id'], outcome, evidence_version, json.dumps(outcome_data), time.time()))
            # A quarantined plausible candidate is not evidence that a different candidate is correct.
            if plan['suspect']:
                continue
            # A second plausible candidate vetoes automatic contextual resolution.
            if len(plan['matches']) != 1:
                continue
            target, decision = plan['matches'][0]
            if decision['method'] == 'contextual' and any(
                    decisions[p].get('decision') != 'separate' for p in plan['pairs']
                    if pair_plans[p][1]['id'] != target['id']):
                continue
            if matching.blocked(db, [mention['id'], target['id']]):
                continue
            data = dict(**decision, active=True, policy=POLICY, hash=entities.entry_hash(entry),
                        target_signature=target_signature(target, souls.get(target['id'], entity_soul.empty())),
                        original_label=mention['label'], created=datetime.now(timezone.utc).isoformat())
            data['evidence_hashes'] = {e['id']: e['content_hash'] for e in target['entries']
                                      if e.get('content_hash') and e['id'] in decision.get('evidence_entry_ids', [])}
            if any(i not in latest or entities.entry_hash(latest[i]) != h for i, h in data['evidence_hashes'].items()):
                continue
            previous = db.execute('SELECT data FROM entity_resolutions WHERE entry_id=? AND mention_id=?',
                                  (entry['id'], mention['id'])).fetchone()
            previous_data = json.loads(previous[0]) if previous else {}
            if {k:v for k,v in previous_data.items() if k != 'created'} == {k:v for k,v in data.items() if k != 'created'}:
                continue
            db.execute('INSERT OR REPLACE INTO entity_resolutions VALUES (?,?,?,?)',
                       (entry['id'], mention['id'], target['id'], json.dumps(data)))
            entity_merges.record_event(db, target['id'], 'mention-resolved', 'entity-resolver',
                                      {'name': target['label'], 'entry_id': entry['id'], 'mention_id': mention['id'],
                                       'before': previous_data, 'resolution': data}, deliver=False)
            db.execute("UPDATE entity_resolution_outcomes SET outcome='resolved',data=? WHERE entry_id=? AND mention_id=?",
                       (json.dumps(dict(target_id=target['id'])), entry['id'], mention['id']))
        for job in jobs:
            db.execute('DELETE FROM entity_resolution_jobs WHERE entry_id=? AND revision=?',
                       (job['entry_id'], job['revision']))
        pending = db.execute('SELECT count(*) FROM entity_resolution_jobs').fetchone()[0]
    return {'processed': len(jobs), 'pending': pending}


def process_pending(use_model=True):
    """Bounded worker: a bad entry backs off without starving later entries."""
    if not matching.enabled():
        return dict(state='disabled', processed=0, pending=0)
    store = get_store()
    store.state('resolution-last-started', time.time())
    with store.connection() as db:
        jobs = list(db.execute("""SELECT * FROM entity_resolution_jobs WHERE state='pending'
            AND next_attempt<=? ORDER BY created_at,entry_id LIMIT 8""", (time.time(),)))
    processed, errors = 0, []
    for job in jobs:
        try:
            processed += process_batch(use_model=use_model, entry_id=job['entry_id'])['processed']
            store.state('resolution-last-success', time.time())
            with store.connection() as db:
                db.execute('DELETE FROM state WHERE key=?', ('resolution-error:' + job['entry_id'],))
        except Exception as exc:
            attempts = job['attempts'] + 1
            error = type(exc).__name__  # Avoid persisting provider credentials or source payloads.
            with store.connection() as db:
                db.execute("""UPDATE entity_resolution_jobs SET attempts=?,next_attempt=?,state=?,error=?
                    WHERE entry_id=? AND revision=?""",
                    (attempts, time.time() + min(3600, 30 * 2 ** (attempts - 1)),
                     'failed' if attempts >= 5 else 'pending', error, job['entry_id'], job['revision']))
            from workflows.hfl.entity_model_response import EntityModelResponseError
            details = exc.diagnostics if isinstance(exc, EntityModelResponseError) else {}
            failure = dict(entry_id=job['entry_id'], error=error, diagnostics=details)
            store.state('resolution-error:' + job['entry_id'], details)
            store.state('resolution-last-error', dict(at=time.time(), **failure))
            errors.append(failure)
    with store.connection() as db:
        db.execute("""INSERT INTO state VALUES ('resolution-completed',?) ON CONFLICT(key)
            DO UPDATE SET value=CAST(CAST(value AS INTEGER)+? AS TEXT)""", (str(processed), processed))
        ready = db.execute("SELECT count(*) FROM entity_resolution_jobs WHERE state='pending' AND next_attempt<=?",
                           (time.time(),)).fetchone()[0]
        next_attempt = db.execute("SELECT min(next_attempt) FROM entity_resolution_jobs WHERE state='pending'").fetchone()[0]
    store.state('resolution-last-finished', time.time())
    result = dict(state='partial-failure' if errors and processed else 'failed' if errors else 'complete',
                  processed=processed, pending=ready, errors=errors,
                  retry_after=max(2, min(3600, int(next_attempt-time.time())+1)) if next_attempt and not ready else None)
    store.state('resolution-last-result', dict(at=time.time(), **result))
    return result


def undo(entry_id, mention_id, actor):
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM entity_resolutions WHERE entry_id=? AND mention_id=?', (entry_id, mention_id)).fetchone()
        if not row:
            raise ValueError('Resolution unavailable')
        data = json.loads(row['data'])
        data['active'] = False
        matching.block_members(db, [mention_id, row['target_id']], 'resolution-undone')
        db.execute('UPDATE entity_resolutions SET data=? WHERE entry_id=? AND mention_id=?',
                   (json.dumps(data), entry_id, mention_id))
        entity_merges.record_event(db, row['target_id'], 'resolution-undone', actor,
                                  {'entry_id': entry_id, 'mention_id': mention_id}, deliver=False)
    return {'state': 'undone'}


def status():
    with get_store().connection() as db:
        pending = db.execute("SELECT count(*) FROM entity_resolution_jobs WHERE state='pending'").fetchone()[0]
        failed = db.execute("SELECT count(*) FROM entity_resolution_jobs WHERE state='failed'").fetchone()[0]
        oldest = db.execute("SELECT min(created_at) FROM entity_resolution_jobs WHERE state='pending'").fetchone()[0]
        retrying = db.execute("SELECT count(*) FROM entity_resolution_jobs WHERE state='pending' AND attempts>0").fetchone()[0]
        outcomes = dict(db.execute('SELECT outcome,count(*) FROM entity_resolution_outcomes GROUP BY outcome'))
        failures = [dict(r) for r in db.execute("""SELECT entry_id,attempts,error,next_attempt,state
            FROM entity_resolution_jobs WHERE attempts>0 ORDER BY created_at LIMIT 20""")]
        for failure in failures:
            row = db.execute('SELECT value FROM state WHERE key=?', ('resolution-error:' + failure['entry_id'],)).fetchone()
            failure['diagnostics'] = json.loads(row[0]) if row else {}
    store = get_store()
    return dict(pending=pending, failed=failed, retrying=retrying, oldest_pending_at=oldest,
                oldest_pending_age_seconds=max(0, time.time()-oldest) if oldest else None,
                policy=POLICY, enabled=matching.enabled(), outcomes=outcomes, failures=failures,
                last_success=store.state('resolution-last-success'), last_error=store.state('resolution-last-error'),
                last_started=store.state('resolution-last-started'), last_finished=store.state('resolution-last-finished'),
                last_dispatch=store.state('resolution-last-dispatch'),
                dispatch_error=store.state('resolution-dispatch-error'),
                last_result=store.state('resolution-last-result'),
                cached_comparisons=store.state('resolution-cache-hits') or 0,
                evaluated_comparisons=store.state('resolution-comparisons') or 0,
                received=store.state('resolution-received') or 0, completed=store.state('resolution-completed') or 0)


def retry_failed(entry_id):
    with get_store().connection() as db:
        count = db.execute("""UPDATE entity_resolution_jobs SET state='pending',attempts=0,next_attempt=0,queued_at=0
            WHERE entry_id=? AND state='failed'""", (entry_id,)).rowcount
    return {'requeued': count}


def invalidate_targets(db, identities):
    """Do not resurrect an old assignment if a merge is later undone."""
    for identity in identities:
        db.execute("UPDATE entity_resolutions SET data=json_set(data, '$.active', json('false')) WHERE target_id=?",
                   (identity,))
