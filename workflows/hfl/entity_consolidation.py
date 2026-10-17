"""Durable Hermes runs. Agents propose; this service validates and commits."""
from datetime import datetime
import json
import logging
from copy import deepcopy
import os
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from filelock import FileLock

from workflows.hfl import entity_matching as matching, entity_merges
from workflows.hfl.entity_candidates import AUDIT_SOURCES, CandidateIndex, activity_count, candidates, preferred, similarity
from workflows.hfl.entity_store import digest, get_store
from workflows.hfl.entity_run_storage import read_run, write_run

POLICY = 'hermes-entity-consolidation-v1'
DISCOVERY_VERSION = 'exact-stars-v2'
SKILL = Path(__file__).resolve().parents[2] / '.agents/skills/auto-merge-entities/SKILL.md'
log = logging.getLogger(__name__)


def current_entities():
    from modules.hfl_corpus.entities import entity_index
    rows = entity_index()
    with get_store().connection() as db:
        groups = {r['id']: json.loads(r['members']) for r in db.execute('SELECT id,members FROM entity_merges')}
    for row in rows:
        row['entries'] = [e for e in row['entries'] if e.get('source') not in AUDIT_SOURCES]
        # Legacy merged groups predate the editable alias property.
        if row['id'] in groups:
            profile = dict(row.get('profile') or {})
            aliases = list(profile.get('aliases', []))
            sources = dict(profile.get('alias_sources', {}))
            stack, seen = [row['id']], set()
            while stack:
                identity = stack.pop()
                if identity in seen:
                    continue
                seen.add(identity)
                for member in groups.get(identity, []):
                    if member['label'] != row['label'] and member['label'] not in aliases:
                        aliases.append(member['label'])
                        sources[member['label']] = 'merged-name'
                    stack.append(member['id'])
            profile.update(aliases=aliases, alias_sources=sources)
            row['profile'] = profile
    return rows


def signature(entity):
    return digest(entity)


def evidence(entity):
    result = matching.evidence_entity(entity)
    # Hints aid discovery but are not corroborating facts.
    result['hints'] = {k: (entity.get('profile') or {}).get(k, []) for k in ('aliases', 'partial_aliases')}
    from workflows.hfl.entity_evidence import select_activity
    result['activity'], result['excluded_activity'], result['activity_total'] = select_activity(entity['entries'])
    result['evidence_version'] = 2
    result['related_items'] = activity_count(entity)
    return result


def load(run_id):
    started = time.perf_counter()
    with get_store().connection() as db:
        run = read_run(db, run_id)
    if not run:
        raise ValueError('Unknown consolidation run')
    metric(run, 'load', time.perf_counter() - started)
    return run


def save(run):
    started = time.perf_counter()
    with get_store().connection() as db:
        write_run(db, run)
    # Log the actual write duration without a second write solely for timing.
    log.info('entity-consolidation run=%s operation=save seconds=%.6f pairs=%d',
             run['id'], time.perf_counter() - started, len(run['pairs']))


def begin():
    store = get_store()
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        active = store.state('consolidation-active')
        if active:
            prior = load(active)
            if prior['state'] == 'running':
                return view(prior)
        run_id = datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
        with store.connection() as db:
            existing = read_run(db, run_id)
        if existing:
            return view(existing)
        rows = current_entities()
        by_id = {e['id']: e for e in rows}
        previous = store.state('consolidation-checkpoint') or {}
        snapshots = {e['id']: signature(e) for e in rows}
        changed = {i for i, value in snapshots.items() if previous.get(i) != value}
        if store.state('consolidation-discovery-version') != DISCOVERY_VERSION:
            changed = set(snapshots)
        run = dict(id=run_id, state='running', created=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(),
                   policy=POLICY, skill_hash=digest(SKILL.read_text(encoding='utf-8')),
                   discovery_version=DISCOVERY_VERSION,
                   snapshots=snapshots, discovery_snapshots=dict(snapshots),
                   pairs={}, delivery={}, initial=not bool(previous))
        evidence_cache = {}
        with store.connection() as db:
            pairs = candidates(rows, changed, index=CandidateIndex(rows, persistent=True))
            # Existing review suggestions participate in the first pass even when
            # their names do not meet the new discovery threshold.
            if not previous:
                for row in db.execute("SELECT left_id,right_id FROM entity_match_pairs WHERE state='suggested'"):
                    pair = tuple(sorted(store.resolve(i) for i in row))
                    if len(set(pair)) == 2 and all(i in by_id for i in pair):
                        pairs.append(pair)
            for left, right in sorted(set(pairs)):
                if by_id[left]['kind'] != by_id[right]['kind'] or matching.blocked(db, [left, right]):
                    continue
                pair_id = digest([left, right])
                for identity in (left, right):
                    if identity not in evidence_cache:
                        evidence_cache[identity] = evidence(by_id[identity])
                run['pairs'][pair_id] = dict(id=pair_id, ids=[left, right], state='pending',
                    queued_at=time.time(),
                    snapshots={i: snapshots[i] for i in (left, right)},
                    kind=by_id[left]['kind'], left=evidence_cache[left], right=evidence_cache[right],
                    signals=similarity(by_id[left], by_id[right]), preferred_id=preferred([by_id[left], by_id[right]])['id'])
        # The owner switch and initial work intent are atomic. Queued old tasks
        # see this owner before applying another automatic merge.
        with store.connection() as db:
            db.execute("UPDATE entity_match_jobs SET state='delegated' WHERE state IN ('pending','running')")
            write_run(db, run)
            for key, value in [('entity-consolidation-owner', 'hermes'), ('consolidation-active', run_id)]:
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))
        return view(run)


TYPE_PRIORITY = ('people', 'companies', 'tools', 'pets', 'apps', 'games')


def pair_priority(pair):
    """Frequency chooses the work anchor, never the canonical merge name."""
    anchor, other = sorted((pair['left'], pair['right']),
                           key=lambda e: (-e.get('related_items', 0), e['id']))
    kind = pair['kind']
    signals = pair.get('signals', {})
    return (TYPE_PRIORITY.index(kind) if kind in TYPE_PRIORITY else len(TYPE_PRIORITY),
            -anchor.get('related_items', 0), anchor['id'],
            -bool(signals.get('contact')), -bool(signals.get('exact')),
            -bool(signals.get('partial')), -signals.get('fuzzy', 0),
            -other.get('related_items', 0), pair['id'])


def view(run, offset=0, limit=20):
    pairs = list(run['pairs'].values())
    counts = {s: sum(p['state'] == s for p in pairs) for s in ('pending', 'merged', 'deferred', 'separate', 'stale')}
    pending = sorted((p for p in pairs if p['state'] == 'pending'), key=pair_priority) if limit else []
    return {k: run[k] for k in ('id', 'state', 'initial', 'delivery')} | {
        'capabilities': ['atomic-anchor-groups-v1', 'anchor-packets-v1',
                         'claimed-anchor-packets-v1', 'consolidation-batch-v2'],
        'metrics': run.get('metrics', {}), 'checkpoint': run.get('checkpoint'),
        'merged_groups': merged_group_count(pairs),
        'counts': counts, 'pairs': pending[offset:offset+limit], 'pending_total': counts['pending']}


def compact_view(result):
    """Deduplicate evidence losslessly and propose disjoint, unapproved stars."""
    evidence_by_id, pairs, groups, used = {}, [], [], set()
    for pair in result['pairs']:
        for side in ('left', 'right'):
            entity = pair[side]
            previous = evidence_by_id.setdefault(entity['id'], entity)
            if previous != entity:
                raise ValueError('Inconsistent evidence snapshots; do not deduplicate')
        pairs.append({k: v for k, v in pair.items() if k not in ('left', 'right')} | {
            'left_id': pair['left']['id'], 'right_id': pair['right']['id']})
    def rank(entity):
        kind = entity['kind']
        return (TYPE_PRIORITY.index(kind) if kind in TYPE_PRIORITY else len(TYPE_PRIORITY),
                -entity.get('related_items', 0), entity['id'])
    assigned = set()
    for anchor in sorted(evidence_by_id.values(), key=rank):
        if anchor['id'] in used:
            continue
        edges = [p for p in pairs if anchor['id'] in p['ids'] and not used.intersection(p['ids'])]
        if not edges:
            continue
        groups.append({'anchor_id': anchor['id'], 'pair_ids': [p['id'] for p in edges]})
        used.update(i for p in edges for i in p['ids'])
        assigned.update(p['id'] for p in edges)
    return result | {'format': 'anchor-packets-v1', 'entities': evidence_by_id,
                     'pairs': pairs, 'groups': groups,
                     'ungrouped_pair_ids': [p['id'] for p in pairs if p['id'] not in assigned]}


def corroborated(decision, pair):
    from workflows.hfl.entity_evidence import fact_origins
    if decision.get('decision') != 'merge' or decision.get('contradictions') or not decision.get('reason'):
        return False
    a, b = pair['left'].get('external_id'), pair['right'].get('external_id')
    if a and b and a != b:
        return False
    facts, origins = fact_origins(decision, pair)
    # Ordinary matches need independently sourced facts on BOTH sides. Different
    # excerpts of one capture must never count as independent evidence.
    if all(len(values) >= 2 for values in origins.values()) and matching.supported(decision, pair):
        return True
    signals = pair['signals']
    return bool(facts) and bool(signals['exact'] or signals['fuzzy'] >= .88 or signals['contact'])


def invalidate(run, ids):
    for pair in run['pairs'].values():
        if pair['state'] == 'pending' and set(ids).intersection(pair['ids']):
            pair.update(state='stale', note='Endpoint changed; fresh evidence required, not a carried-over approval')


def metric(run, name, elapsed):
    metrics = run.setdefault('metrics', {})
    values = metrics.setdefault(name, {'calls': 0, 'seconds': 0})
    values['calls'] += 1
    values['seconds'] += elapsed


def live_snapshot(run):
    started = time.perf_counter()
    with get_store().connection() as db:
        revision = entity_merges.revision(db)
    live = {e['id']: e for e in current_entities()}
    metric(run, 'entity_index', time.perf_counter() - started)
    return live, revision


def decide(run_id, pair_id, decision, claim_token=None):
    store = get_store()
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        run = load(run_id)
        pair = _decide(run, pair_id, decision, claim_token)
        save(run)
        return pair


def decide_batch(run_id, decisions, claim_token=None):
    """One lock/load/save, with individual merge receipts and partial results."""
    if not 1 <= len(decisions) <= 20:
        raise ValueError('A batch requires 1–20 decisions')
    store = get_store()
    started = time.perf_counter()
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        lock_wait = time.perf_counter() - started
        run = load(run_id)
        metric(run, 'lock_wait', lock_wait)
        results = []
        try:
            for pair_id, decision in decisions.items():
                before = deepcopy(run['pairs'].get(pair_id))
                try:
                    pair = _decide(run, pair_id, decision, claim_token)
                    results.append({'id': pair_id, 'state': pair['state'],
                        'operation': pair.get('operation'), 'note': pair.get('note')})
                except ValueError as exc:
                    if before is not None:
                        run['pairs'][pair_id] = before
                    results.append({'id': pair_id, 'error': str(exc)})
        finally:
            metric(run, 'batch', time.perf_counter() - started)
            save(run)
        return {'results': results, 'metrics': run.get('metrics', {})}


def _decide(run, pair_id, decision, claim_token=None):
    from modules.hfl_corpus.entity_merge_api import MergePreview, build_preview
    from modules.hfl_corpus.entities_api import Profile, validated_profile
    run_id = run['id']
    pair = run['pairs'].get(pair_id)
    if not pair:
        raise ValueError('Pair is outside this run')
    request_id = str(uuid5(NAMESPACE_URL, POLICY + run_id + pair_id))
    fingerprint = digest(decision)
    receipt = entity_merges.operation(request_id, fingerprint)
    if receipt:
        event = next(e for e in entity_merges.history(receipt['entity_id']) if e['id'] == receipt['event_id'])
        pair.update(state='merged', operation=receipt, decision=decision,
                    result_name=event['data']['name'], related_items=event['data']['unique_entries'])
        invalidate(run, pair['ids'])
        return pair
    if pair['state'] != 'pending':
        if pair.get('decision') != decision:
            raise ValueError('Decision already recorded; cannot replace it')
        return pair
    if run['state'] != 'running':
        raise ValueError('Run is closed')
    from workflows.hfl.entity_consolidation_work import check_claim
    check_claim(run, pair['ids'], claim_token)
    pair['decision'] = decision
    if decision['decision'] != 'merge':
        pair['state'] = 'separate' if decision['decision'] == 'separate' else 'deferred'
        return pair
    live, observed_revision = live_snapshot(run)
    ids = pair['ids']
    if any(i not in live or signature(live[i]) != run['snapshots'][i] for i in ids):
        pair.update(state='stale', note='Evidence changed; reconsider on next run')
        return pair
    for side in ('left', 'right'):
        if pair[side].get('evidence_version') != 2:
            pair[side] = evidence(live[pair[side]['id']])
    if decision.get('contradictions') or not corroborated(decision, pair):
        pair.update(state='deferred', note='Insufficient corroboration or conflicting evidence')
    else:
        selected = [live[i] for i in ids]
        curated = [e for e in selected if matching.curated_profile(e)]
        explicit = [e for e in selected if (e.get('profile') or {}).get('preferred_name')]
        if len(curated) > 1 or len(explicit) > 1:
            pair.update(state='deferred', note='Conflicting curated identities require review')
        else:
            target = preferred(selected)
            preview = build_preview(MergePreview(entity_ids=ids, name=target['label'], evidence=decision['reason']), current=list(live.values()))
            if preview['revision'] != observed_revision:
                raise ValueError('Entities changed during assessment; request fresh evidence')
            profile = preview['profile']
            sources = profile['alias_sources']
            for key in ('aliases', 'partial_aliases'):
                for alias in decision.get(key, []):
                    if alias not in profile[key]:
                        profile[key].append(alias)
                        sources[alias] = 'llm'
            validated = validated_profile(Profile(**profile))
            validated['alias_sources'] = sources
            if curated:
                other = next(e for e in selected if e['id'] != target['id'])
                validated['notes'] = (target.get('profile') or {}).get('notes', '')
                if (other.get('profile') or {}).get('notes'):
                    validated['notes'] += '\n\n' + other['profile']['notes']
            preview['profile'] = validated
            preview['automatic'] = dict(run_id=run_id, policy=POLICY, skill_hash=run['skill_hash'],
                decision=decision, input_hash=digest(pair), protected_profile=bool(curated))
            started = time.perf_counter()
            receipt = entity_merges.commit_merge(preview, request_id, fingerprint, 'entity-matcher:hermes')
            metric(run, 'merge_commit', time.perf_counter() - started)
            pair.update(state='merged', operation=receipt, result_name=target['label'], related_items=preview['unique_entries'])
            invalidate(run, ids)
    return pair


def merge_group(run_id, payload, claim_token=None):
    """Commit a corroborated star, not sequential overlapping pair merges."""
    from modules.hfl_corpus.entity_merge_api import MergePreview, build_preview
    from modules.hfl_corpus.entities_api import Profile, validated_profile
    anchor = payload['anchor_id']
    decisions = payload['decisions']
    if not 2 <= len(decisions) <= 20:
        raise ValueError('A group requires 2–20 anchor-pair decisions')
    store = get_store()
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        run = load(run_id)
        pairs = [run['pairs'].get(i) for i in sorted(decisions)]
        if any(p is None or anchor not in p['ids'] for p in pairs):
            raise ValueError('Every pair must belong to this run and share the explicit anchor')
        ids = sorted({i for p in pairs for i in p['ids']})
        if len(ids) != len(pairs) + 1 or len({p['kind'] for p in pairs}) != 1:
            raise ValueError('A group must contain distinct same-type anchor pairs')
        group_id = str(uuid5(NAMESPACE_URL, POLICY + run_id + ':group:' + digest(sorted(decisions))))
        fingerprint = digest(payload)
        receipt = entity_merges.operation(group_id, fingerprint)
        if not receipt:
            from workflows.hfl.entity_consolidation_work import check_claim
            check_claim(run, ids, claim_token)
            if run['state'] != 'running' or any(p['state'] != 'pending' for p in pairs):
                raise ValueError('Group requires pending pairs in a running run')
            if any(set(p['ids']).issubset(ids) and (p['state'] == 'separate'
                   or p.get('decision', {}).get('contradictions')) for p in run['pairs'].values()):
                raise ValueError('Existing cross-member separate decision or contradiction blocks this group')
            live, observed_revision = live_snapshot(run)
            if any(i not in live or signature(live[i]) != run['snapshots'][i] for i in ids):
                raise ValueError('Group evidence changed; reconsider from a fresh run')
            for pair in pairs:
                for side in ('left', 'right'):
                    if pair[side].get('evidence_version') != 2:
                        pair[side] = evidence(live[pair[side]['id']])
            if payload.get('contradictions') or any(
                decisions[p['id']]['decision'] != 'merge' or decisions[p['id']].get('contradictions')
                or not corroborated(decisions[p['id']], p) for p in pairs
            ):
                raise ValueError('Every member needs independent corroboration without contradictions')
            selected = [live[i] for i in ids]
            if len({e['external_id'] for e in selected if e.get('external_id')}) > 1:
                raise ValueError('Conflicting external identities across group members')
            curated = [e for e in selected if matching.curated_profile(e)]
            explicit = [e for e in selected if (e.get('profile') or {}).get('preferred_name')]
            if len(curated) > 1 or len(explicit) > 1:
                raise ValueError('Conflicting curated identities require review')
            target = preferred(selected)
            reasons = '\n'.join(decisions[p['id']]['reason'] for p in pairs)
            preview = build_preview(MergePreview(entity_ids=ids, name=target['label'], evidence=reasons[:10000]), current=list(live.values()))
            if preview['revision'] != observed_revision:
                raise ValueError('Entities changed during group assessment; request fresh evidence')
            profile = preview['profile']
            sources = profile['alias_sources']
            for decision in decisions.values():
                for key in ('aliases', 'partial_aliases'):
                    for alias in decision.get(key, []):
                        if alias not in profile[key]:
                            profile[key].append(alias)
                            sources[alias] = 'llm'
            validated = validated_profile(Profile(**profile))
            validated['alias_sources'] = sources
            if curated:
                validated['notes'] = '\n\n'.join((e.get('profile') or {}).get('notes', '')
                    for e in [target] + [e for e in selected if e['id'] != target['id']]
                    if (e.get('profile') or {}).get('notes'))
            preview['profile'] = validated
            preview['automatic'] = dict(run_id=run_id, policy=POLICY, skill_hash=run['skill_hash'],
                group=payload, input_hash=digest(pairs), protected_profile=bool(curated))
            started = time.perf_counter()
            receipt = entity_merges.commit_merge(preview, group_id, fingerprint, 'entity-matcher:hermes')
            metric(run, 'merge_commit', time.perf_counter() - started)
        # Receipt-first recovery also repairs a crash after commit and before run save.
        event = next(e for e in entity_merges.history(receipt['entity_id']) if e['id'] == receipt['event_id'])
        result = dict(group_id=group_id, pair_ids=sorted(decisions), state='merged', operation=receipt,
                      result_name=event['data']['name'], related_items=event['data']['unique_entries'])
        for pair in pairs:
            pair.update({k: v for k, v in result.items() if k != 'pair_ids'}, decision=decisions[pair['id']])
        invalidate(run, ids)
        save(run)
        return result


def finish(run_id):
    store = get_store()
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        run = load(run_id)
        if run['state'] == 'complete':
            return view(run)
        if any(p['state'] == 'pending' for p in run['pairs'].values()):
            raise ValueError('Record decisions for pending pairs before finishing')
        run['state'] = 'complete'
        # Record evaluated snapshots, not post-merge signatures: newly formed
        # groups and changed evidence must participate on the next daily run.
        with store.connection() as db:
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('consolidation-checkpoint', json.dumps(run['snapshots'])))
            if run.get('discovery_version') == DISCOVERY_VERSION:
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                           ('consolidation-discovery-version', json.dumps(DISCOVERY_VERSION)))
            write_run(db, run)
        return view(run)


def merged_group_count(pairs):
    """N approved anchor edges can share one reversible merge operation."""
    return len({p.get('operation', {}).get('event_id') or p['id']
                for p in pairs if p['state'] == 'merged'})


def report(run):
    lines = [f"# Entity consolidation — {run['id']}", f"Run: {run['state']}; policy: {run['policy']}"]
    groups = {}
    for pair in run['pairs'].values():
        groups.setdefault(pair['kind'], []).append(pair)
    if not groups:
        lines.append('No new matching candidates; no changes.')
    for kind, pairs in sorted(groups.items()):
        lines += ['', '## ' + kind, f"{merged_group_count(pairs)} merged groups; {len(pairs)} comparisons"]
        for p in pairs:
            lines.append(f"- {p['left']['name']} ({p['left']['related_items']} items) + {p['right']['name']} ({p['right']['related_items']} items): {p['state']}")
            if p.get('operation'):
                lines.append(f"  → {p.get('result_name', 'merged identity')}; {p.get('related_items', 'see audit')} unique items; undo identity: {p['operation']['entity_id']}; event: {p['operation']['event_id']}")
            lines.append('  ' + p.get('note', p.get('decision', {}).get('reason', 'Awaiting agent decision')))
            for key in ('aliases', 'partial_aliases'):
                if p['state'] == 'merged' and p.get('decision', {}).get(key):
                    lines.append(f"  Generated {key}: {', '.join(p['decision'][key])}")
    return '\n'.join(lines)


def dispatch_reports(run_id=None):
    """Recover committed report intents through the existing HFL outbox sweep."""
    from workflows.hfl.tasks.entity_consolidation import deliver_entity_consolidation
    store = get_store()
    dispatched = []
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        with store.connection() as db:
            runs = [json.loads(r[0]) for r in db.execute("SELECT value FROM state WHERE key LIKE 'consolidation:%' AND json_extract(value, '$.state') = 'complete' AND coalesce(json_extract(value, '$.delivery.telegram_state'), '') NOT IN ('sent', 'sending', 'suppressed')")]
        for run in runs:
            run = load(run['id'])
            delivery = run['delivery']
            if run_id and run['id'] != run_id:
                continue
            if run['state'] != 'complete' or delivery.get('telegram_state') in {'sent', 'sending', 'suppressed'}:
                continue
            if delivery.get('queued_at', 0) > time.time() - 600:
                continue
            task = deliver_entity_consolidation.apply_async(kwargs={'run_id': run['id']},
                queue=os.environ.get('HARQIS_ENTITIES_QUEUE', 'hfl'))
            delivery.update(task_id=task.id, queued_at=time.time())
            save(run)
            dispatched.append(task.id)
    return dispatched
