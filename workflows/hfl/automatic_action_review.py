"""Bounded automatic-action review planning and fail-closed decision validation.

No provider or storage access here. A batch is approved only after every shard
has been reviewed; partitioning never removes an evidence/comparison record.
"""
from __future__ import annotations

import json

MAX_REVIEW_CHARS = 250000
MAX_REVIEW_SHARDS = 32


class AutomaticActionReviewError(ValueError):
    """Content-free diagnostics; never interpolate evidence or model output."""

    def __init__(self, reason, stage, **counts):
        self.reason = reason
        self.stage = stage
        self.counts = counts
        super().__init__('Automatic action review could not safely finish.')

    def diagnostic(self):
        return {'reason': self.reason, 'stage': self.stage, **self.counts}


def review_shards(candidates, snapshot, evidence, redact):
    """Preflight the entire bounded plan before making any paid requests.

    Repeat the complete candidate batch, preserving within-batch comparisons.
    Records are indivisible. A batch that cannot fit even without context fails
    closed rather than silently shortening candidates or their evidence links.
    """
    fields = ('existing_actions', 'dismissed_ideas', 'evidence')
    actions = [{key: item.get(key) for key in
                ('id', 'title', 'expected_outcome', 'status', 'source')}
               for item in snapshot['actions']]
    dismissed = [{key: item.get(key) for key in
                  ('id', 'title', 'expected_outcome', 'source')}
                 for item in snapshot['dismissed_ideas']]

    def empty():
        return {'candidates': candidates, **{field: [] for field in fields}}

    def encode(value):
        return redact(json.dumps(value, ensure_ascii=False))

    current = empty()
    if len(encode(current)) > MAX_REVIEW_CHARS:
        raise AutomaticActionReviewError('oversized_candidates', 'planning', candidates=len(candidates))
    shards = []
    # Evidence first lets the final comparison shard veto provisional approvals.
    for field, records in [('evidence', evidence), ('existing_actions', actions), ('dismissed_ideas', dismissed)]:
        for record in records:
            current[field].append(record)
            if len(encode(current)) <= MAX_REVIEW_CHARS:
                continue
            current[field].pop()
            if any(current[name] for name in fields):
                shards.append(current)
            current = empty()
            current[field].append(record)
            if len(encode(current)) > MAX_REVIEW_CHARS:
                raise AutomaticActionReviewError('oversized_record', 'planning', candidates=len(candidates))
            if len(shards) >= MAX_REVIEW_SHARDS:
                raise AutomaticActionReviewError('review_budget_exhausted', 'planning',
                                                shard_limit=MAX_REVIEW_SHARDS)
    shards.append(current)
    return [(value, encode(value)) for value in shards]


def validate_decisions(candidates, decisions, actions, dismissed):
    """Validate every decision before any persistence, including unknown IDs."""
    def invalid():
        raise AutomaticActionReviewError('invalid_decisions', 'validation', candidates=len(candidates))

    identities = [item['id'] for item in candidates]
    if (len(set(identities)) != len(identities) or not isinstance(decisions, list)
            or len(decisions) != len(identities)):
        invalid()
    by_id = {}
    for item in decisions:
        if not isinstance(item, dict) or not isinstance(item.get('suggestion_id'), str):
            invalid()
        identity = item['suggestion_id']
        if identity not in identities or identity in by_id:
            invalid()
        by_id[identity] = item
    existing = {item['id'] for item in actions}
    suppressed = {item['id'] for item in dismissed}
    earlier = set()
    ordered = []
    for identity in identities:
        item = by_id[identity]
        choice = item.get('decision')
        if not isinstance(choice, str) or choice not in {'create', 'duplicate', 'defer'}:
            invalid()
        for field, allowed in [('confidence', {'high', 'medium', 'low'}),
                               ('completion_check', {'clear', 'uncertain', 'resolved'})]:
            if field in item and (not isinstance(item[field], str) or item[field] not in allowed):
                invalid()
        if 'reason' in item and not isinstance(item['reason'], str):
            invalid()
        action = item.get('existing_action_id', '')
        suggestion = item.get('duplicate_suggestion_id', '')
        if not isinstance(action, str) or not isinstance(suggestion, str):
            invalid()
        if choice == 'duplicate':
            if bool(action) == bool(suggestion):
                invalid()
            if (action and action not in existing) or (suggestion and suggestion not in suppressed | earlier):
                invalid()
        elif action or suggestion:
            invalid()
        if choice == 'create' and (item.get('confidence') != 'high'
                or item.get('completion_check') != 'clear'
                or not isinstance(item.get('reason'), str) or not item['reason'].strip()):
            invalid()
        ordered.append(dict(item))
        earlier.add(identity)
    return ordered


def merge_decisions(candidates, reviews):
    """Only unanimous provisional approval permits creation; doubt is sticky."""
    merged = []
    resolved = {}
    for index, candidate in enumerate(candidates):
        values = [review[index] for review in reviews]
        # A resolved/uncertain completion check vetoes creation even if another
        # shard found a duplicate. Never reopen anything on a mixed judgment.
        selected = next((item for item in values if item['decision'] == 'defer'
                         or item.get('completion_check') in {'uncertain', 'resolved'}), None)
        if selected is not None:
            selected = {'suggestion_id': candidate['id'], 'decision': 'defer',
                        'reason': 'At least one review partition requires manual review.'}
        else:
            selected = dict(next((item for item in values if item['decision'] == 'duplicate'), values[0]))
            target = selected.get('duplicate_suggestion_id')
            if target in resolved:
                prior = resolved[target]
                if prior['decision'] == 'defer':
                    selected = {'suggestion_id': candidate['id'], 'decision': 'defer',
                                'reason': 'Equivalent earlier candidate requires manual review.'}
                elif prior['decision'] == 'duplicate':
                    selected['existing_action_id'] = prior.get('existing_action_id', '')
                    selected['duplicate_suggestion_id'] = prior.get('duplicate_suggestion_id', '')
        merged.append(selected)
        resolved[candidate['id']] = selected
    return merged
