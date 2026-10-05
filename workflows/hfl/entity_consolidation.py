"""Durable Hermes runs. Agents propose; this service validates and commits."""
from datetime import datetime
import json
import os
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from filelock import FileLock

from workflows.hfl import entity_matching as matching, entity_merges
from workflows.hfl.entity_candidates import AUDIT_SOURCES, activity_count, candidates, preferred, similarity
from workflows.hfl.entity_store import digest, get_store

POLICY = 'hermes-entity-consolidation-v1'
SKILL = Path(__file__).resolve().parents[2] / '.agents/skills/auto-merge-entities/SKILL.md'


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
    result['related_items'] = activity_count(entity)
    return result


def load(run_id):
    run = get_store().state('consolidation:' + run_id)
    if not run:
        raise ValueError('Unknown consolidation run')
    return run


def save(run):
    get_store().state('consolidation:' + run['id'], run)


def begin():
    store = get_store()
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        active = store.state('consolidation-active')
        if active:
            prior = load(active)
            if prior['state'] == 'running':
                return view(prior)
        run_id = datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
        existing = store.state('consolidation:' + run_id)
        if existing:
            return view(existing)
        rows = current_entities()
        by_id = {e['id']: e for e in rows}
        previous = store.state('consolidation-checkpoint') or {}
        snapshots = {e['id']: signature(e) for e in rows}
        changed = {i for i, value in snapshots.items() if previous.get(i) != value}
        run = dict(id=run_id, state='running', created=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(),
                   policy=POLICY, skill_hash=digest(SKILL.read_text(encoding='utf-8')),
                   snapshots=snapshots, pairs={}, delivery={}, initial=not bool(previous))
        with store.connection() as db:
            pairs = candidates(rows, changed)
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
                run['pairs'][pair_id] = dict(id=pair_id, ids=[left, right], state='pending',
                    kind=by_id[left]['kind'], left=evidence(by_id[left]), right=evidence(by_id[right]),
                    signals=similarity(by_id[left], by_id[right]), preferred_id=preferred([by_id[left], by_id[right]])['id'])
        # The owner switch and initial work intent are atomic. Queued old tasks
        # see this owner before applying another automatic merge.
        with store.connection() as db:
            db.execute("UPDATE entity_match_jobs SET state='delegated' WHERE state IN ('pending','running')")
            for key, value in [('entity-consolidation-owner', 'hermes'), ('consolidation-active', run_id),
                               ('consolidation:' + run_id, run)]:
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))
        return view(run)


def view(run, offset=0, limit=20):
    pairs = list(run['pairs'].values())
    counts = {s: sum(p['state'] == s for p in pairs) for s in ('pending', 'merged', 'deferred', 'separate', 'stale')}
    pending = [p for p in pairs if p['state'] == 'pending']
    return {k: run[k] for k in ('id', 'state', 'initial', 'delivery')} | {
        'counts': counts, 'pairs': pending[offset:offset+limit], 'pending_total': len(pending)}


def corroborated(decision, pair):
    if matching.supported(decision, pair):
        return True
    a, b = pair['left'].get('external_id'), pair['right'].get('external_id')
    if a and b and a != b:
        return False
    signals = pair['signals']
    if not (signals['exact'] or signals['fuzzy'] >= .88 or signals['contact']):
        return False
    # Sparse typo evidence may contain just one activity, but it must supply a
    # substantial, specific fact on each side, not the alias itself.
    for fact in decision.get('facts', []):
        if all(isinstance(fact.get(side+'_quote'), str) and len(fact[side+'_quote']) >= 25
               and len(fact[side+'_quote'].split()) >= 5
               and any(fact[side+'_quote'] in a['text'] for a in pair[side]['activity'])
               for side in ('left', 'right')) and fact.get('explanation'):
            return True
    return False


def decide(run_id, pair_id, decision):
    from modules.hfl_corpus.entity_merge_api import MergePreview, build_preview
    from modules.hfl_corpus.entities_api import Profile, validated_profile
    store = get_store()
    with FileLock(str(store.path) + '.matching.lock', timeout=30):
        run = load(run_id)
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
            save(run)
            return pair
        if pair['state'] != 'pending':
            if pair.get('decision') != decision:
                raise ValueError('Decision already recorded; cannot replace it')
            return pair
        if run['state'] != 'running':
            raise ValueError('Run is closed')
        pair['decision'] = decision
        if decision['decision'] != 'merge':
            pair['state'] = 'separate' if decision['decision'] == 'separate' else 'deferred'
            save(run)
            return pair
        live = {e['id']: e for e in current_entities()}
        ids = pair['ids']
        if any(i not in live or signature(live[i]) != run['snapshots'][i] for i in ids):
            pair.update(state='stale', note='Evidence changed; reconsider on next run')
        elif decision.get('contradictions') or not corroborated(decision, pair):
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
                receipt = entity_merges.commit_merge(preview, request_id, fingerprint, 'entity-matcher:hermes')
                pair.update(state='merged', operation=receipt, result_name=target['label'], related_items=preview['unique_entries'])
        save(run)
        return pair


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
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('consolidation:'+run_id, json.dumps(run)))
        return view(run)


def report(run):
    lines = [f"# Entity consolidation — {run['id']}", f"Run: {run['state']}; policy: {run['policy']}"]
    groups = {}
    for pair in run['pairs'].values():
        groups.setdefault(pair['kind'], []).append(pair)
    if not groups:
        lines.append('No new matching candidates; no changes.')
    for kind, pairs in sorted(groups.items()):
        lines += ['', '## ' + kind, f"{sum(p['state']=='merged' for p in pairs)} merged groups; {len(pairs)} comparisons"]
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
