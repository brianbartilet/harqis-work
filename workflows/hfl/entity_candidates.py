"""Deterministic discovery and ranking; similarity is never identity approval."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from workflows.hfl.entity_matching import normalize

AUDIT_SOURCES = {'entities-audit', 'entity-consolidation'}


def activity_count(entity):
    return len({e['id'] for e in entity.get('entries', []) if e.get('source') not in AUDIT_SOURCES})


def names(entity):
    profile = entity.get('profile') or {}
    return {normalize(n) for n in [entity['label'], *profile.get('aliases', [])] if normalize(n)}


def similarity(left, right, name_sets=None):
    a, b = name_sets if name_sets is not None else (names(left), names(right))
    exact = bool(a & b)
    partial = any(normalize(h) in n for e, other in ((left, b), (right, a))
                  for h in (e.get('profile') or {}).get('partial_aliases', [])
                  if len(normalize(h)) >= 3 for n in other)
    fuzzy = max((SequenceMatcher(None, x, y).ratio() for x in a for y in b), default=0)
    contacts = any(set((left.get('profile') or {}).get(k, [])) &
                   set((right.get('profile') or {}).get(k, [])) for k in ('emails', 'phones', 'references'))
    return {'exact': exact, 'partial': partial, 'fuzzy': round(fuzzy, 4), 'contact': contacts}


def candidates(entities, seeds=None, per_entity=5):
    """Use same-type trigram/token postings to avoid an all-pairs comparison."""
    postings, keys = defaultdict(set), {}
    by_id = {e['id']: e for e in entities}
    name_values = {e['id']: names(e) for e in entities}
    for e in entities:
        values = name_values[e['id']] | {normalize(x) for x in (e.get('profile') or {}).get('partial_aliases', [])}
        tokens = {('gram', n[i:i+3]) for n in values for i in range(len(n)-2)}
        tokens |= {('word', w) for n in values for w in n.split() if len(w) >= 3}
        tokens |= {('name', n) for n in name_values[e['id']]}
        tokens |= {('contact', v) for k in ('emails', 'phones', 'references') for v in (e.get('profile') or {}).get(k, [])}
        keys[e['id']] = tokens
        for key in tokens:
            postings[(e['kind'], key)].add(e['id'])
    pairs = set()
    for e in entities:
        if seeds is not None and e['id'] not in seeds:
            continue
        overlaps = Counter()
        for key in keys[e['id']]:
            weight = 100 if key[0] in {'name', 'contact'} else 4 if key[0] == 'word' else 1
            for identity in postings[(e['kind'], key)]:
                if identity != e['id']:
                    overlaps[identity] += weight
        # Bound expensive edit-distance work even for common tokens such as
        # "project". Exact aliases/contact IDs receive priority in this pool.
        possible = sorted(overlaps, key=lambda i: (-overlaps[i] / (len(keys[e['id']]) + len(keys[i])),
                                                   -activity_count(by_id[i]), i))[:50]
        ranked = []
        for identity in possible:
            other = by_id[identity]
            s = similarity(e, other, (name_values[e['id']], name_values[identity]))
            if s['exact'] or s['partial'] or s['contact'] or s['fuzzy'] >= .8:
                ranked.append((-(4*s['contact'] + 3*s['exact'] + 2*s['partial'] + s['fuzzy']),
                               -activity_count(other), identity))
        for _, _, identity in sorted(ranked)[:per_entity]:
            pairs.add(tuple(sorted((e['id'], identity))))
    return sorted(pairs)


def preferred(entities):
    from workflows.hfl.entity_matching import curated_profile
    return min(entities, key=lambda e: (not (e.get('profile') or {}).get('preferred_name', False),
                                        not curated_profile(e), -activity_count(e), e['id']))
