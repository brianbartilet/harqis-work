"""Durable, disjoint review leases. Agents review; the existing service commits."""
import json
import time
from uuid import uuid4

from filelock import FileLock

from workflows.hfl import entity_consolidation as runs, entity_matching as matching
from workflows.hfl.entity_candidates import CandidateIndex, candidates, similarity, preferred
from workflows.hfl.entity_store import digest, get_store


def active_claims(run):
    return {key: value for key, value in run.get('claims', {}).items()
            if value['expires_at'] > time.time()}


def check_claim(run, ids, token):
    claims = active_claims(run)
    if token is not None:
        claim = claims.get(token)
        if not claim or not set(ids).issubset(claim['entity_ids']):
            raise ValueError('Review claim expired or does not cover these entities; claim fresh work')
    if any(key != token and set(ids).intersection(value['entity_ids']) for key, value in claims.items()):
        raise ValueError('Entities are claimed by another reviewer')


def reconcile(run, live):
    """Retire stale work before model review, including legacy pair-merge leftovers."""
    signatures = {i: runs.signature(e) for i, e in live.items()}
    run.setdefault('discovery_snapshots', dict(run['snapshots']))
    changed = {i for i, value in run['snapshots'].items() if signatures.get(i) != value}
    runs.invalidate(run, changed)
    # Upgrade legacy evidence only when the underlying entity is unchanged.
    for pair in run['pairs'].values():
        if pair['state'] == 'pending':
            for side in ('left', 'right'):
                if pair[side].get('evidence_version') != 2:
                    pair[side] = runs.evidence(live[pair[side]['id']])
    defer_unusable(run)
    return signatures


def defer_unusable(run):
    for pair in run['pairs'].values():
        if pair['state'] == 'pending' and any(
            not pair[side]['activity'] and pair[side].get('excluded_activity') for side in ('left', 'right')
        ):
            pair.update(state='deferred', note='No corroborating activity on an endpoint; excluded provenance retained, identity not adjudicated')


def discover(run, live, signatures, seeds, index=None):
    """Bounded expansion, never an assertion that the candidate graph is complete."""
    existing = {tuple(p['ids']) for p in run['pairs'].values() if p['state'] != 'stale'
                and all(p.get('snapshots', run['snapshots']).get(i) == signatures.get(i) for i in p['ids'])}
    added = 0
    # Reuse hydrated evidence for unchanged entities when a new neighbor arrives.
    # Otherwise one entity can acquire conflicting packets within the same run.
    evidence_cache = {p[side]['id']: p[side] for p in run['pairs'].values()
        if p['state'] == 'pending' for side in ('left', 'right')
        if p.get('snapshots', run['snapshots']).get(p[side]['id']) == signatures.get(p[side]['id'])}
    with get_store().connection() as db:
        for left, right in candidates(list(live.values()), seeds, per_entity=20, index=index):
            if (left, right) in existing or matching.blocked(db, [left, right]):
                continue
            pair_id = digest([left, right, signatures[left], signatures[right]])
            if pair_id in run['pairs']:
                if run['pairs'][pair_id]['state'] != 'stale':
                    continue
                # Evidence may return to an earlier version after an edit. Keep
                # the old stale record and issue fresh work without its verdict.
                pair_id = digest([pair_id, len(run['pairs'])])
            for identity in (left, right):
                if identity not in evidence_cache:
                    evidence_cache[identity] = runs.evidence(live[identity])
            run['pairs'][pair_id] = dict(id=pair_id, ids=[left, right], state='pending',
                snapshots={i: signatures[i] for i in (left, right)},
                kind=live[left]['kind'], left=evidence_cache[left], right=evidence_cache[right],
                signals=similarity(live[left], live[right]), preferred_id=preferred([live[left], live[right]])['id'])
            added += 1
    run['snapshots'].update(signatures)
    defer_unusable(run)
    return added


def packet(run, claim, summary=None):
    result = dict(summary if summary is not None else runs.view(run, limit=0))
    result['pairs'] = [run['pairs'][i] for i in claim['pair_ids']]
    result = runs.compact_view(result)
    # The claimed anchor, not a second page-local heuristic, owns this packet.
    result['groups'] = [dict(anchor_id=claim['anchor_id'], pair_ids=claim['pair_ids'],
                            entity_ids=claim['entity_ids'])]
    result['ungrouped_pair_ids'] = []
    result['claim'] = claim
    result['evidence_bytes'] = len(json.dumps({k: result[k] for k in ('entities', 'pairs')},
                                            ensure_ascii=False).encode('utf-8'))
    return result


def claim_work(run_id, options):
    worker = options['worker_id']
    limit = options.get('max_pairs', 8)
    budget = options.get('max_bytes', 100000)
    duration = options.get('lease_seconds', 900)
    if not worker or not 1 <= limit <= 20 or not 4096 <= budget <= 1000000 or not 60 <= duration <= 3600:
        raise ValueError('Invalid worker, packet budget or lease duration')
    started = time.perf_counter()
    with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
        run = runs.load(run_id)
        if run['state'] != 'running':
            raise ValueError('Run is closed')
        live, _ = runs.live_snapshot(run)
        signatures = reconcile(run, live)
        changed = {i for i, value in signatures.items() if run['discovery_snapshots'].get(i) != value}
        index = CandidateIndex(list(live.values()), persistent=True)
        added = discover(run, live, signatures, changed, index) if changed else 0
        run['discovery_snapshots'] = signatures
        run['checkpoint'] = {'at': time.time(), 'added': added,
                             'counts': runs.view(run, limit=0)['counts']}
        run['claims'] = active_claims(run)
        for token, claim in list(run['claims'].items()):
            if not all(run['pairs'][i]['state'] == 'pending' for i in claim['pair_ids']):
                del run['claims'][token]
            elif claim['worker_id'] == worker:
                runs.save(run)
                return packet(run, claim)
        busy = {i for c in run['claims'].values() for i in c['entity_ids']}
        pending = sorted((p for p in run['pairs'].values() if p['state'] == 'pending'
                          and not busy.intersection(p['ids'])), key=runs.pair_priority)
        if not pending:
            runs.save(run)
            return runs.compact_view(runs.view(run, limit=0)) | {'claim': None, 'waiting': bool(run['claims'])}
        seed = pending[0]
        anchor = min((seed['left'], seed['right']), key=lambda e: (-e['related_items'], e['id']))['id']
        # Expand this anchor once per evidence version. The whole neighborhood is
        # selected BEFORE applying packet limits; continuation stays explicit.
        expansions = run.setdefault('expanded_anchors', {})
        if expansions.get(anchor) != signatures[anchor]:
            added += discover(run, live, signatures, {anchor}, index)
            expansions[anchor] = signatures[anchor]
        run['checkpoint'].update(added=added, counts=runs.view(run, limit=0)['counts'])
        edges = sorted((p for p in run['pairs'].values() if p['state'] == 'pending'
                        and anchor in p['ids'] and not busy.intersection(p['ids'])), key=runs.pair_priority)
        claim = dict(token=uuid4().hex, worker_id=worker, anchor_id=anchor,
                     pair_ids=[], entity_ids=[], expires_at=time.time() + duration,
                     remaining_for_anchor=0)
        summary = runs.view(run, limit=0)
        for edge in edges[:limit]:
            proposed = dict(claim, pair_ids=[*claim['pair_ids'], edge['id']],
                            entity_ids=sorted(set(claim['entity_ids']) | set(edge['ids'])))
            size = packet(run, proposed, summary)['evidence_bytes']
            if size > budget:
                if not claim['pair_ids']:
                    runs.save(run)
                    return {'claim': None, 'required_bytes': size, 'max_bytes': budget,
                            'anchor_id': anchor, 'pending_total': runs.view(run, limit=0)['pending_total']}
                break
            claim = proposed
        claim['remaining_for_anchor'] = len(edges) - len(claim['pair_ids'])
        run['claims'][claim['token']] = claim
        runs.metric(run, 'claim', time.perf_counter() - started)
        runs.save(run)
        return packet(run, claim, summary)


def update_claim(run_id, token, action, lease_seconds=900):
    if action not in {'renew', 'release'} or not 60 <= lease_seconds <= 3600:
        raise ValueError('Invalid claim action or lease duration')
    with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
        run = runs.load(run_id)
        claims = active_claims(run)
        if action == 'release':
            claims.pop(token, None)  # Releasing twice is harmless.
        else:
            claim = claims.get(token)
            if not claim or not all(run['pairs'][i]['state'] == 'pending' for i in claim['pair_ids']):
                raise ValueError('Claim expired or changed; claim fresh work')
            claim['expires_at'] = time.time() + lease_seconds
        run['claims'] = claims
        runs.save(run)
        return {'token': token, 'action': action, 'expires_at': claims.get(token, {}).get('expires_at')}


def checkpoint(run_id):
    """Persist partial progress and discover changed inputs without closing the run."""
    with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
        run = runs.load(run_id)
        if run['state'] != 'running':
            raise ValueError('Run is closed')
        live, _ = runs.live_snapshot(run)
        signatures = reconcile(run, live)
        previous = run.get('discovery_snapshots', run['snapshots'])
        changed = {i for i, value in signatures.items() if previous.get(i) != value}
        added = discover(run, live, signatures, changed,
                         CandidateIndex(list(live.values()), persistent=True))
        run['discovery_snapshots'] = signatures
        run['claims'] = active_claims(run)
        run['checkpoint'] = {'at': time.time(), 'added': added,
                             'counts': runs.view(run, limit=0)['counts']}
        runs.save(run)
        return runs.view(run, limit=0)


def expand_evidence(run_id, entity_id, entry_ids, claim_token=None):
    """Hydrate selected original entries once and reuse them across pending pairs."""
    from modules.hfl_corpus import entities
    from workflows.hfl.entity_evidence import activity
    if not 1 <= len(set(entry_ids)) <= 4:
        raise ValueError('Select 1–4 original entries')
    with FileLock(str(get_store().path) + '.matching.lock', timeout=30):
        run = runs.load(run_id)
        if run['state'] != 'running':
            raise ValueError('Run is closed')
        check_claim(run, [entity_id], claim_token)
        live, revision = runs.live_snapshot(run)
        entity = live.get(entity_id)
        if entity is None or runs.signature(entity) != run['snapshots'].get(entity_id):
            raise ValueError('Entity changed; claim fresh evidence')
        available = {e['id']: e for e in entity['entries']}
        if not set(entry_ids).issubset(available):
            raise ValueError('Entry is not supporting evidence for this entity')
        originals = {e['id']: e for e in entities.current_entries() if e['id'] in entry_ids}
        hydrated = []
        for entry_id in entry_ids:
            original = originals.get(entry_id)
            if original is None or entities.entry_hash(original) != available[entry_id].get('content_hash'):
                raise ValueError('Original entry changed; claim fresh evidence')
            row = activity(available[entry_id])
            text = original['text']
            position = text.find(available[entry_id]['evidence'])
            start = max(0, position - 1500)
            row.update(text=text[start:start + 6000], truncated=len(text) > 6000,
                       expanded=True, content_hash=available[entry_id]['content_hash'])
            # Classification sees original context, not only a name-only snippet.
            from workflows.hfl.entity_evidence import directory_capture
            if directory_capture(dict(available[entry_id], evidence=text)):
                row['corroborating'] = False
            hydrated.append(row)
        with get_store().connection() as db:
            if runs.entity_merges.revision(db) != revision:
                raise ValueError('Entities changed while retrieving evidence; retry')
        updated = None
        for pair in run['pairs'].values():
            if pair['state'] != 'pending':
                continue
            for side in ('left', 'right'):
                if pair[side]['id'] != entity_id:
                    continue
                evidence = pair[side]
                keep = [a for a in evidence['activity'] if a['id'] not in entry_ids]
                evidence['activity'] = [a for a in hydrated if a['corroborating']] + keep
                evidence['activity'] = evidence['activity'][:12]
                excluded = [a for a in evidence.get('excluded_activity', []) if a['id'] not in entry_ids]
                evidence['excluded_activity'] = ([a for a in hydrated if not a['corroborating']] + excluded)[:8]
                updated = evidence
        if updated is None:
            raise ValueError('No pending comparison uses this entity')
        runs.save(run)
        return updated
