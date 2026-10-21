"""Fail-closed matcher response parsing with payload-free diagnostics."""
import json
import re


class EntityModelResponseError(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__('Entity matcher response rejected: ' + diagnostics['reason'])

    def __reduce__(self):
        return type(self), (self.diagnostics,)


def parse_decisions(response, pair_ids):
    stop = getattr(response, 'stop_reason', None)
    diagnostics = {'stop_reason': stop if stop in {
        'end_turn', 'max_tokens', 'stop_sequence', 'tool_use', 'pause_turn', 'refusal'
    } else 'unknown'}
    usage = getattr(response, 'usage', None)
    for key in ('input_tokens', 'output_tokens'):
        value = getattr(usage, key, None)
        if isinstance(value, int):
            diagnostics[key] = value

    def reject(reason, **details):
        raise EntityModelResponseError({**diagnostics, 'reason': reason, **details}) from None

    if stop != 'end_turn':
        reject('truncated' if stop == 'max_tokens' else 'incomplete-response')
    blocks = getattr(response, 'content', []) or []
    texts = [b.text for b in blocks if getattr(b, 'type', None) == 'text' and isinstance(getattr(b, 'text', None), str)]
    if not texts:
        reject('missing-text')
    raw = ''.join(texts).strip()
    diagnostics.update(text_blocks=len(texts), response_chars=len(raw))
    fenced = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\s*```', raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        reject('invalid-json', line=exc.lineno, column=exc.colno, position=exc.pos)
    if not isinstance(data, dict) or not isinstance(data.get('decisions'), list):
        reject('invalid-decision-list')
    decisions = data['decisions']
    seen = set()
    expected = set(pair_ids)
    for decision in decisions:
        if not isinstance(decision, dict):
            reject('invalid-decision')
        identity = decision.get('id')
        if not isinstance(identity, str) or identity not in expected or identity in seen:
            reject('unexpected-or-duplicate-id')
        seen.add(identity)
        if (decision.get('decision') not in ('merge', 'review', 'separate')
                or not isinstance(decision.get('reason'), str)
                or not isinstance(decision.get('contradictions'), list)
                or not all(isinstance(v, str) for v in decision['contradictions'])
                or not isinstance(decision.get('facts'), list)):
            reject('invalid-decision')
        for fact in decision['facts']:
            if not isinstance(fact, dict) or not all(isinstance(fact.get(k), str)
                    for k in ('left_quote', 'right_quote', 'explanation')):
                reject('invalid-fact')
    if seen != expected:
        reject('missing-decisions', expected=len(expected), received=len(seen))
    return decisions
