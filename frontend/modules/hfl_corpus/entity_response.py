"""Fail-closed parsing at the entity model's untrusted response boundary."""
import json
import re


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Entity response contains duplicate JSON keys')
        value[key] = item
    return value


def _reject_constant(_value):
    raise ValueError('Entity response contains nonstandard JSON constants')


def parse_response(response):
    """Accept one complete object, optionally fenced/surrounded by commentary.

    Unlike distill.parse_model_json, invalid output must raise, not become an
    empty successful extraction. Never recover a nested object from bad JSON or
    choose one of several objects. Error messages exclude private model text.
    """
    if getattr(response, 'stop_reason', None) not in (None, 'end_turn', 'stop_sequence'):
        raise ValueError('Entity response did not finish normally')
    text = '\n'.join(block.text for block in response.content
                     if getattr(block, 'type', 'text') == 'text'
                     and isinstance(getattr(block, 'text', None), str)).strip()
    start = re.search(r'[\[{}\]]', text)
    if not start or start.group() != '{':
        raise ValueError('Entity response requires a JSON object')
    prefix = text[:start.start()]
    try:
        result, end = json.JSONDecoder(
            object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        ).raw_decode(text, start.start())
    except json.JSONDecodeError:
        raise ValueError('Entity response contains malformed JSON') from None
    suffix = text[end:]
    if '```' in prefix:
        opening = re.search(r'```(?:json)?\s*$', prefix, re.IGNORECASE)
        closing = re.match(r'\s*```', suffix)
        if not opening or not closing:
            raise ValueError('Entity response has incomplete JSON fencing')
        prefix, suffix = prefix[:opening.start()], suffix[closing.end():]
    # Check both boundaries independently: whole-string loads misses scalars
    # mixed with prose and incomplete JSON fragments. Treat ambiguous tokens as
    # JSON, while allowing ordinary prose (including its commas and colons).
    extra_json = (
        r'[\[{}\]"]|```|(?:^|\s)[,:]'
        r'|(?<!\w)(?:null|true|false|NaN|-?Infinity'
        r'|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?!\w)'
    )
    if any(re.search(extra_json, boundary) for boundary in (prefix, suffix)):
        raise ValueError('Entity response contains ambiguous extra JSON')
    if not isinstance(result, dict) or not isinstance(result.get('entries'), list):
        raise ValueError('Entity response requires an entries list')
    seen = set()
    for row in result['entries']:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not row['id'] or not isinstance(row.get('mentions'), list)):
            raise ValueError('Entity response contains an invalid entry')
        if row['id'] in seen:
            raise ValueError('Entity response contains duplicate entry IDs')
        seen.add(row['id'])
        for item in row['mentions']:
            if (not isinstance(item, dict)
                    or not all(isinstance(item.get(key), str) for key in ('kind', 'name', 'evidence'))):
                raise ValueError('Entity response contains an invalid mention')
    return result
