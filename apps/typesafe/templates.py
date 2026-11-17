"""Versioned questions and provisional review policy, kept together for audit."""
import json
import re

TEMPLATE = 'action_triage_v1'
POLICY = {'suitable_min': .8, 'choice_min': .8, 'missing_max': .2, 'margin_min': .2}
URGENCY = ['Can wait', 'Needs attention this week', 'Needs attention today']


def text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def build(template, state):
    if template != TEMPLATE:
        raise ValueError('Unknown decision template; use action_triage_v1.')
    if not isinstance(state, dict) or set(state) != {'action', 'candidate_agents'}:
        raise ValueError('State requires only action and candidate_agents.')
    action, candidates = state['action'], state['candidate_agents']
    if (not isinstance(action, dict) or set(action) != {'title', 'description'}
            or not text(action['title'], 500) or not text(action['description'], 16000)):
        raise ValueError('Action requires a title (1–500 characters) and description (1–16000).')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 20:
        raise ValueError('Supply 1–20 candidate agents; an empty candidate set requires manual review.')
    criteria, mapping = {}, {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != {'id', 'name', 'capabilities'}:
            raise ValueError('Each candidate requires only id, name and capabilities.')
        identity, name, capabilities = candidate['id'], candidate['name'], candidate['capabilities']
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', identity):
            raise ValueError('Invalid candidate ID.')
        if identity in mapping.values() or not text(name, 200):
            raise ValueError('Candidate IDs must be unique and names must be 1–200 characters.')
        if not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 20 or not all(text(c, 500) for c in capabilities):
            raise ValueError('Supply 1–20 bounded capability descriptions per candidate.')
        # Human-readable choice keys help the model; map back to opaque IDs in code.
        key = f'{name.strip()} [{index + 1}]'
        criteria[key] = '; '.join(capabilities)
        mapping[key] = identity
    if len(json.dumps(state, ensure_ascii=False).encode()) > 48_000:
        raise ValueError('Decision state exceeds 48 KB; supply focused context.')
    questions = {
        'suitable': {'type': 'noul', 'instructions': 'Does any candidate have the capabilities needed for the action?'},
        'agent': {'type': 'choice', 'instructions': 'Which candidate is best suited to perform the action?', 'criteria': criteria},
        'urgency': {'type': 'score', 'instructions': 'How urgent is the action based on the supplied facts?', 'criteria': URGENCY},
        'missing': {'type': 'noul', 'instructions': 'Is essential information missing that prevents work on the action?'}
    }
    return questions, mapping


def interpret(answers, mapping):
    choice = answers['agent']['choice']
    probabilities = answers['agent']['probabilities']
    others = [v for k, v in probabilities.items() if k != choice]
    reasons = []
    if answers['suitable']['noul'] < POLICY['suitable_min']:
        reasons.append('no_clear_suitable_candidate')
    if answers['missing']['noul'] > POLICY['missing_max']:
        reasons.append('missing_information')
    if probabilities[choice] < POLICY['choice_min'] or probabilities[choice] - max(others, default=0) < POLICY['margin_min']:
        reasons.append('ambiguous_choice')
    return {'status': 'needs_review' if reasons else 'recommendation',
            'recommended_agent_id': None if reasons else mapping[choice],
            'reason_codes': reasons, 'execution_authorized': False}
