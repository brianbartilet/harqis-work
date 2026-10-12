"""Bounded evidence packets with source lineage, not just repeated quotations."""
import re

from workflows.hfl.entity_store import digest


def directory_capture(entry):
    """Only explicit provenance or a captured directory UI is non-corroborating."""
    if entry.get('evidence_role') == 'directory':
        return True
    source = entry.get('source', '').casefold()
    text = (entry.get('title', '') + '\n' + entry.get('evidence', '')).casefold()
    capture = any(word in source for word in ('screen', 'capture', 'browser', 'desktop'))
    directory = '/hfl-corpus/entities' in text or 'harqis entity directory' in text
    return capture and directory


def activity(entry):
    text = entry.get('evidence') or ''
    # Exact copies across ingest sources share an origin unless an upstream
    # origin is provided. This is deliberately conservative, not semantic proof.
    origin = entry.get('origin_id') or digest(re.sub(r'\s+', ' ', text).strip().casefold())
    return dict(id=entry['id'], text=text[:2000], source=entry.get('source', ''),
                date=entry.get('date', ''), title=entry.get('title', ''),
                locator=entry.get('href', ''), origin_id=origin,
                corroborating=bool(text.strip()) and not directory_capture(entry),
                truncated=len(text) > 2000)


def select_activity(entries, limit=8):
    """Prefer diverse sources and origins; retain excluded provenance separately."""
    rows = [activity(e) for e in entries]
    remaining = [r for r in rows if r['corroborating']]
    selected, sources, origins = [], set(), set()
    while remaining and len(selected) < limit:
        row = max(remaining, key=lambda r: (r['origin_id'] not in origins,
            r['source'] not in sources, len(r['text']), r['date'], r['id']))
        remaining.remove(row)
        selected.append(row)
        sources.add(row['source'])
        origins.add(row['origin_id'])
    excluded = [r for r in rows if not r['corroborating']]
    return selected, excluded[:limit], len(rows)


def fact_origins(decision, pair):
    """Resolve quotes to eligible source IDs; distinguish independent origins."""
    origins = {'left': set(), 'right': set()}
    valid_facts = []
    for fact in decision.get('facts', []):
        matches = {}
        for side in ('left', 'right'):
            quote = fact.get(side + '_quote', '')
            entry_id = fact.get(side + '_entry_id')
            if not isinstance(quote, str) or len(quote) < 25 or len(quote.split()) < 5:
                break
            matches[side] = [a for a in pair[side]['activity']
                if a.get('corroborating', True) and quote in a['text']
                and (entry_id is None or a['id'] == entry_id)]
            if not matches[side]:
                break
        else:
            if not fact.get('explanation'):
                continue
            valid_facts.append(fact)
            for side in ('left', 'right'):
                # Ambiguous quotes do not get credit for every matching source.
                row = matches[side][0]
                origins[side].add(row.get('origin_id', row['id']))
    return valid_facts, origins
