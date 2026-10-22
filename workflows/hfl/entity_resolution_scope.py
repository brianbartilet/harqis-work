"""Resolver dependencies shared by targeted scheduling and optimistic validation."""
import json
from collections import defaultdict

from workflows.hfl.entity_store import digest, identity_resolver
from workflows.hfl.entity_candidates import CandidateIndex, feature_input, search_features
from workflows.hfl.entity_matching import normalize


class Scope:
    """Read one SQLite snapshot; never open another connection during validation."""

    def __init__(self, db):
        self.resolve = identity_resolver(db)
        self.tables = {table: [dict(r) for r in db.execute('SELECT * FROM ' + table)] for table in (
            'enrichment', 'profiles', 'decisions', 'entity_merges', 'entity_souls',
            'entity_activity_links', 'entity_resolutions', 'entity_match_blocks', 'entity_integrity')}
        self.records = {r['id']: r for r in self.tables['enrichment']}
        self.children = defaultdict(set)
        for r in self.tables['decisions']:
            if r['active']:
                self.children[r['canonical']].add(r['alias'])
        for r in self.tables['entity_merges']:
            self.children[r['id']].update(m['id'] for m in json.loads(r['members']))
        self.mentions = {i: json.loads(r['mentions']) for i, r in self.records.items()}
        self.by_identity = defaultdict(set)
        for entry_id, mentions in self.mentions.items():
            for mention in mentions:
                self.by_identity[mention['id']].add(entry_id)
                self.by_identity[self.resolve(mention['id'])].add(entry_id)
        for link in self.tables['entity_activity_links']:
            self.by_identity[self.resolve(link['entity_id'])].add(link['entry_id'])
        self.souls = {r['id']: json.loads(r['data']) for r in self.tables['entity_souls']}
        self.rules = defaultdict(set)
        for identity, soul in self.souls.items():
            for rule in soul.get('identity_rules', []):
                self.rules[normalize(rule['observed_name'])].add(identity)
        inactive = {r['id'] for r in self.tables['entity_merges'] if not r['active']}
        self.index = CandidateIndex([
            dict(id=r['id'], kind=r['kind'], label=json.loads(r['data'])['name'],
                 profile=json.loads(r['data']), entries=[])
            for r in self.tables['profiles'] if self.resolve(r['id']) == r['id'] and r['id'] not in inactive])
        self.previous = defaultdict(set)
        for r in self.tables['entity_resolutions']:
            self.previous[r['entry_id']].add(r['target_id'])
        for r in db.execute('SELECT entry_id,data FROM entity_resolution_outcomes'):
            self.previous[r['entry_id']].update(json.loads(r['data']).get('candidate_ids', []))

    def identities(self, entry_id):
        identities = set(self.previous[entry_id])
        for mention in self.mentions.get(entry_id, []):
            identities.update((mention['id'], self.resolve(mention['id'])))
            if not mention.get('label') or not mention.get('kind'):
                continue  # Legacy/incomplete extraction cannot participate in discovery.
            # Include the discovery pool, not just yesterday's five candidates:
            # a new competitor or changed ranking must invalidate the assessment.
            _, keys = search_features(feature_input(mention))
            for key in keys:
                identities.update(self.index.postings.get((mention['kind'], key), ()))
            identities.update(self.rules.get(normalize(mention['label']), ()))
        for identity in list(identities):
            identities.update(r['target_id'] for r in self.souls.get(identity, {}).get('relationships', []))
        pending = list(identities)
        while pending:
            identity = pending.pop()
            for related in self.children[identity] | {self.resolve(identity)}:
                if related not in identities:
                    identities.add(related)
                    pending.append(related)
        return identities

    def evidence_ids(self, entry_id, identities=None):
        identities = self.identities(entry_id) if identities is None else identities
        return {entry_id} | {e for i in identities for e in self.by_identity[i]}

    def signature(self, entry_id):
        ids = self.identities(entry_id)
        entries = self.evidence_ids(entry_id, ids)
        selected = {}
        for table, rows in self.tables.items():
            if table == 'enrichment':
                values = [r for r in rows if r['id'] in entries]
            elif table == 'decisions':
                values = [r for r in rows if r['active'] and (r['alias'] in ids or r['canonical'] in ids)]
            elif table == 'entity_match_blocks':
                values = [r for r in rows if r['left_id'] in ids and r['right_id'] in ids]
            elif table == 'entity_activity_links':
                values = [r for r in rows if r['entity_id'] in ids]
            elif table == 'entity_resolutions':
                values = [r for r in rows if r['entry_id'] == entry_id]
            else:
                values = [r for r in rows if r['id'] in ids]
            selected[table] = sorted(values, key=lambda r: json.dumps(r, sort_keys=True))
        return digest(selected)


def enqueue_affected(db, identities, *, invalidate=True):
    """Keep pending work coalesced; reopen only entries depending on this identity."""
    changed = set(identities)
    scope = Scope(db)
    affected = [i for i in scope.records if changed.intersection(scope.identities(i))]
    db.executemany('''INSERT INTO entity_resolution_jobs(entry_id,revision) VALUES (?,?)
        ON CONFLICT(entry_id) DO UPDATE SET revision=excluded.revision,
        attempts=0,next_attempt=0,state='pending',error='' ''',
        [(i, scope.records[i]['hash']) for i in affected])
    # Reconsider previously resolved mentions when a new competitor appears too.
    if invalidate:
        db.executemany("UPDATE entity_resolutions SET data=json_set(data,'$.active',json('false')) WHERE entry_id=?",
                       [(i,) for i in affected])
    return len(affected)
