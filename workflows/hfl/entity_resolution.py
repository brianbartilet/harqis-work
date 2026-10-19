"""Resolve entry mentions to established identities without growing merge trees."""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from workflows.hfl.entity_store import digest, get_store
from workflows.hfl import entity_matching as matching, entity_merges, entity_soul

TASK = 'workflows.knowledge.tasks.connected_hfl.resolve_corpus_entities'
POLICY = 'entity-resolution-v1'


def dispatch_pending():
    if not os.environ.get('HARQIS_ENTITIES_DB') or not matching.enabled():
        return
    from core.apps.sprout.app.celery import SPROUT
    with get_store().connection() as db:
        rows = list(db.execute('SELECT entry_id,revision FROM entity_resolution_jobs WHERE queued_at < ? LIMIT 8',
                               (time.time() - 600,)))
    if not rows:
        return
    try:
        SPROUT.send_task(TASK, queue=os.environ.get('HARQIS_ENTITIES_QUEUE', 'hfl'))
        with get_store().connection() as db:
            db.executemany('UPDATE entity_resolution_jobs SET queued_at=? WHERE entry_id=? AND revision=?',
                           [(time.time(), r['entry_id'], r['revision']) for r in rows])
    except Exception as exc:
        logging.getLogger(__name__).warning('Entity resolution intent retained: %s', type(exc).__name__)


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


def process_batch(use_model=True):
    if not matching.enabled():
        return {'state': 'disabled', 'processed': 0, 'pending': 0}
    from modules.hfl_corpus import entities
    from workflows.hfl.entity_candidates import CandidateIndex, incoming_candidates, similarity
    from workflows.hfl.entity_consolidation import corroborated, evidence
    store = get_store()
    with store.connection() as db:
        jobs = list(db.execute('SELECT * FROM entity_resolution_jobs ORDER BY rowid LIMIT 8'))
        observed_revision = entity_merges.revision(db)
    if not jobs:
        return {'processed': 0, 'pending': 0}
    entries = {e['id']: e for e in entities.current_entries()}
    records = store.records()
    current = entities.entity_index(resolve_mentions=False)
    labels = {e['id']: e['label'] for e in current}
    # Only established profiles are targets. A raw mention is never its own anchor.
    targets = [e for e in current if e.get('profile')]
    target_ids = {e['id'] for e in targets}
    candidate_index = CandidateIndex(targets)
    souls = entity_soul.all_souls()
    with store.connection() as db:
        already_resolved = assignments(list(entries.values()), store.profiles(), souls, db)
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
            if store.resolve(mention['id']) != mention['id'] or mention['id'] in target_ids:
                continue
            new = {**mention, 'entries': [dict(id=entry['id'], evidence=entry['text'][:16000],
                   source=entry['source'], date=entry['date'], title=entry['title'])]}
            pool = [e for e in targets if e['kind'] == mention['kind'] and e['id'] != mention['id']]
            plan = dict(entry=entry, mention=mention, matches=[], pairs=[])
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
    # Batch pair assessments; provider failures leave durable work untouched.
    decisions = {}
    for offset in range(0, len(model_pairs), 8):
        chunk = model_pairs[offset:offset + 8]
        evaluated, model = matching.evaluate(chunk, immediate=True)
        found = {d.get('id'): d for d in evaluated if isinstance(d, dict)}
        if any(p['id'] not in found for p in chunk):
            raise ValueError('Resolver omitted candidates; retry pending work')
        decisions.update(found)
        for pair in chunk:
            plan, target, original = pair_plans[pair['id']]
            decision = found[pair['id']]
            if corroborated(decision, original):
                supporting_ids = sorted({a['id'] for a in original['right']['activity']
                    if any(f.get('right_quote') and f['right_quote'] in a['text']
                           and (not f.get('right_entry_id') or f['right_entry_id'] == a['id'])
                           for f in decision.get('facts', []) if isinstance(f, dict))})
                plan['matches'].append((target, dict(method='contextual', reason=decision['reason'],
                                                    decision=decision, model=model, evidence_entry_ids=supporting_ids)))
    # Re-read permissions/content before a transactional state revision check.
    latest = {e['id']: e for e in entities.current_entries()}
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if entity_merges.revision(db) != observed_revision:
            raise ValueError('Entity state changed; resolution will retry with current context')
        for plan in plans:
            entry, mention = plan['entry'], plan['mention']
            if entry['id'] not in latest or entities.entry_hash(latest[entry['id']]) != entities.entry_hash(entry):
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
        for job in jobs:
            db.execute('DELETE FROM entity_resolution_jobs WHERE entry_id=? AND revision=?',
                       (job['entry_id'], job['revision']))
        pending = db.execute('SELECT count(*) FROM entity_resolution_jobs').fetchone()[0]
    return {'processed': len(jobs), 'pending': pending}


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
        pending = db.execute('SELECT count(*) FROM entity_resolution_jobs').fetchone()[0]
    return {'pending': pending, 'policy': POLICY, 'enabled': matching.enabled()}


def invalidate_targets(db, identities):
    """Do not resurrect an old assignment if a merge is later undone."""
    for identity in identities:
        db.execute("UPDATE entity_resolutions SET data=json_set(data, '$.active', json('false')) WHERE target_id=?",
                   (identity,))
