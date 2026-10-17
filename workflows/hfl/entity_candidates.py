"""Deterministic discovery and ranking; similarity is never identity approval."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
import json

from workflows.hfl.entity_matching import normalize

AUDIT_SOURCES = {'entities-audit', 'entity-consolidation'}


def activity_count(entity):
    return len({e['id'] for e in entity.get('entries', []) if e.get('source') not in AUDIT_SOURCES})


def names(entity):
    profile = entity.get('profile') or {}
    return {normalize(n) for n in [entity['label'], *profile.get('aliases', [])] if normalize(n)}


@lru_cache(maxsize=20000)
def search_features(encoded):
    """Cache only search inputs; activity/evidence changes never reuse a verdict."""
    entity = json.loads(encoded)
    values = names(entity)
    hints = {normalize(x) for x in entity['profile'].get('partial_aliases', [])}
    keys = {('gram', n[i:i+3]) for n in values | hints for i in range(len(n)-2)}
    keys |= {('word', w) for n in values | hints for w in n.split() if len(w) >= 3}
    keys |= {('name', n) for n in values}
    keys |= {(k, v) for k in ('emails', 'phones', 'references') for v in entity['profile'].get(k, [])}
    return frozenset(values), frozenset(keys)


def feature_input(entity):
    profile = entity.get('profile') or {}
    return json.dumps({'search_version': 2, 'label': entity['label'], 'profile': {
        k: sorted(set(profile.get(k, []))) for k in
        ('aliases', 'partial_aliases', 'emails', 'phones', 'references')}}, sort_keys=True)


class CandidateIndex:
    """One snapshot's postings and counts, shared by discovery and anchor expansion."""

    def __init__(self, entities, *, persistent=False):
        self.by_id = {e['id']: e for e in entities}
        self.counts = {e['id']: activity_count(e) for e in entities}
        self.names, self.keys, self.postings = {}, {}, defaultdict(set)
        stored, updates = {}, []
        if persistent:
            from workflows.hfl.entity_store import get_store
            with get_store().connection() as db:
                stored = {r['id']: r for r in db.execute('SELECT * FROM entity_search_features')}
        for e in entities:
            encoded = feature_input(e)
            old = stored.get(e['id'])
            if old is not None and old['input'] == encoded:
                data = json.loads(old['data'])
                values, keys = frozenset(data[0]), frozenset(tuple(k) for k in data[1])
            else:
                values, keys = search_features(encoded)
                updates.append((e['id'], encoded, json.dumps([sorted(values), sorted(keys)])))
            self.names[e['id']], self.keys[e['id']] = values, keys
            for key in keys:
                self.postings[(e['kind'], key)].add(e['id'])
        if persistent:
            with get_store().connection() as db:
                db.executemany('INSERT OR REPLACE INTO entity_search_features VALUES (?,?,?)', updates)
                db.executemany('DELETE FROM entity_search_features WHERE id=?',
                               [(identity,) for identity in stored.keys() - self.by_id.keys()])
        # Large homogeneous buckets already have complete exact stars. Repeating
        # their word/gram postings for every member would recreate a quadratic scan.
        self.direct_only = {key for key, members in self.postings.items()
                            if len(members) > 256 and len({self.names[i] for i in members}) == 1}

    def rank(self, identity):
        return -self.counts[identity], identity

    def exact_stars(self, seeds):
        """Linear-size exact buckets, not quadratic cliques or identity approvals."""
        pairs = set()
        for (kind, key), members in self.postings.items():
            if key[0] not in {'name', 'emails', 'phones', 'references'} or len(members) < 2:
                continue
            if seeds is not None and not members.intersection(seeds):
                continue
            anchor = min(members, key=self.rank)
            for identity in members:
                if identity != anchor:
                    pairs.add(tuple(sorted((anchor, identity))))
        return pairs


def similarity(left, right, name_sets=None, *, shortlist=False):
    a, b = name_sets if name_sets is not None else (names(left), names(right))
    exact = bool(a & b)
    partial = any(normalize(h) in n for e, other in ((left, b), (right, a))
                  for h in (e.get('profile') or {}).get('partial_aliases', [])
                  if len(normalize(h)) >= 3 for n in other)
    contacts = any(set((left.get('profile') or {}).get(k, [])) &
                   set((right.get('profile') or {}).get(k, [])) for k in ('emails', 'phones', 'references'))
    fuzzy = 1.0 if exact else 0.0
    if not exact:
        for x in a:
            for y in b:
                matcher = SequenceMatcher(None, x, y)
                # Upper bounds cannot discard a qualifying fuzzy candidate.
                # Direct/partial matches retain their original full ranking.
                if shortlist and not (partial or contacts) and (
                    round(matcher.real_quick_ratio(), 4) < .8 or round(matcher.quick_ratio(), 4) < .8
                ):
                    continue
                fuzzy = max(fuzzy, matcher.ratio())
    return {'exact': exact, 'partial': partial, 'fuzzy': round(fuzzy, 4), 'contact': contacts}


def candidates(entities, seeds=None, per_entity=5, *, index=None):
    """Use same-type trigram/token postings to avoid an all-pairs comparison."""
    index = index or CandidateIndex(entities)
    postings, keys, by_id, name_values = index.postings, index.keys, index.by_id, index.names
    pairs = index.exact_stars(seeds)
    for e in entities:
        if seeds is not None and e['id'] not in seeds:
            continue
        overlaps = Counter()
        for key in keys[e['id']]:
            # Direct matches are handled in full above. Skip only homogeneous
            # buckets; common tokens with different names still aid fuzzy recall.
            if (e['kind'], key) in index.direct_only:
                continue
            weight = (100 if key[0] in {'name', 'emails', 'phones', 'references'}
                      else 4 if key[0] == 'word' else 1)
            for identity in postings[(e['kind'], key)]:
                if identity != e['id']:
                    overlaps[identity] += weight
        # Bound expensive edit-distance work even for common tokens such as
        # "project". Exact aliases/contact IDs have their own complete stars.
        possible = sorted(overlaps, key=lambda i: (-overlaps[i] / (len(keys[e['id']]) + len(keys[i])),
                                                   -index.counts[i], i))[:50]
        ranked = []
        for identity in possible:
            other = by_id[identity]
            s = similarity(e, other, (name_values[e['id']], name_values[identity]), shortlist=True)
            if s['exact'] or s['partial'] or s['contact'] or s['fuzzy'] >= .8:
                ranked.append((-(4*s['contact'] + 3*s['exact'] + 2*s['partial'] + s['fuzzy']),
                               -index.counts[identity], identity))
        for _, _, identity in sorted(ranked)[:per_entity]:
            pairs.add(tuple(sorted((e['id'], identity))))
    return sorted(pairs)


def preferred(entities):
    from workflows.hfl.entity_matching import curated_profile
    return min(entities, key=lambda e: (not (e.get('profile') or {}).get('preferred_name', False),
                                        not curated_profile(e), -activity_count(e), e['id']))
