"""Model response formatting must not lose or falsely complete enrichment."""
import json
from types import SimpleNamespace

import pytest

from modules.hfl_corpus import entities
from modules.hfl_corpus.entity_response import parse_response
from workflows.hfl.entity_store import get_store


@pytest.fixture
def extraction(monkeypatch):
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    import apps.antropic.config as config

    row = dict(id='one', text='React is useful.', tags=[], source='notes', date='2026-10-11')
    payload = {'entries': [{'id': 'one', 'mentions': [
        {'kind': 'tools', 'name': 'React', 'evidence': 'React is useful.'}]}]}
    response = SimpleNamespace(content=[], stop_reason='end_turn')
    monkeypatch.setattr(config, 'get_config', lambda name: {})
    monkeypatch.setattr(BaseApiServiceAnthropic, '__init__', lambda self, config: None)
    monkeypatch.setattr(BaseApiServiceAnthropic, 'send_messages', lambda self, **kw: response)
    monkeypatch.setattr(entities.entity_types, 'listing', lambda: [{'id': 'tools'}])
    monkeypatch.setattr(entities, 'current_entries', lambda: [row])

    def set_response(text, stop_reason='end_turn'):
        response.content = [SimpleNamespace(type='text', text=text)]
        response.stop_reason = stop_reason
    return row, payload, response, set_response


@pytest.mark.parametrize('template', [
    '{}', '```json\n{}\n```', '```\n{}\n```',
    '{}\nNo other explicit entities were found.',
    'Here is the extraction:\n{}\nDone.',
    'Here is the extraction:\n```json\n{}\n```\nDone.',
    'Result: {} Done, thanks.',
    'The extraction follows; nullable fields were omitted.\n{}\nNothing else was found!',
])
def test_accepts_one_complete_json_object_with_commentary(extraction, template):
    row, payload, _, set_response = extraction
    set_response(template.format(json.dumps(payload)))
    result = entities.extract_batch([row])
    assert [mention['label'] for mention in result['one']] == ['React']


@pytest.mark.parametrize('text', [
    '', 'No entities.', '{}', '[]', '{"entries": null}',
    '{"entries": [null]}', '{"entries": [{"id": "one"}]}',
    '{"entries": [{"id": [], "mentions": []}]}',
    '{"entries": [{"id": "one", "mentions": null}]}',
    '{"entries": [{"id": "one", "mentions": [null]}]}',
    '{"entries": [{"id": "one", "mentions": [{"kind": []}]}]}',
    '{"entries": [{"id": "one", "mentions": []}, {"id": "one", "mentions": []}]}',
    '{"entries": []}\n{"entries": []}',
    '```json\n{"entries": []}\n```\n```json\n{"entries": []}\n```',
    '{"entries": [{"id": "one", "mentions": []}]',
    '[{"entries": [{"id": "one", "mentions": []}]}]',
])
def test_invalid_or_ambiguous_output_is_not_saved(extraction, text):
    _, _, _, set_response = extraction
    set_response(text)
    with pytest.raises(ValueError):
        entities.enrich()
    assert get_store().records() == {}


@pytest.mark.parametrize('fragment', [
    'null', 'true', 'false', '0', '-12', '1.5', '2e3', '-4.2E-3',
    '"private scalar"', 'NaN', 'Infinity', '-Infinity',
    ',', ':', ',,', '::', ',Done.', ':Done.', ', "entries":', '"entries":', ', "entries"',
    '"unfinished', '[', ']', '{', '}',
])
@pytest.mark.parametrize('side', ['prefix', 'suffix'])
@pytest.mark.parametrize('commentary', [False, True])
def test_rejects_extra_json_boundary_families(extraction, fragment, side, commentary):
    _, payload, _, set_response = extraction
    boundary = f'Here is the result.\n{fragment}\nDone.' if commentary else fragment
    text = json.dumps(payload)
    set_response(f'{boundary}\n{text}' if side == 'prefix' else f'{text}\n{boundary}')
    with pytest.raises(ValueError):
        entities.enrich()
    assert get_store().records() == {}


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity'])
@pytest.mark.parametrize('location', ['root', 'entry', 'mention'])
def test_nonstandard_json_constants_are_rejected_privately(extraction, constant, location):
    _, payload, response, set_response = extraction
    target = {'root': payload, 'entry': payload['entries'][0],
              'mention': payload['entries'][0]['mentions'][0]}[location]
    target['private-key'] = 'CONSTANT_PLACEHOLDER'
    text = json.dumps(payload).replace('"CONSTANT_PLACEHOLDER"', constant)
    set_response(text)
    with pytest.raises(ValueError, match='^Entity response contains nonstandard JSON constants$') as error:
        parse_response(response)
    assert 'private-key' not in str(error.value)
    assert constant not in str(error.value)
    assert error.value.__cause__ is None
    with pytest.raises(ValueError):
        entities.enrich()
    assert get_store().records() == {}


@pytest.mark.parametrize('text, message', [
    ('{"entries": [], "entries": [], "private-key": "private-value"}', 'duplicate JSON keys'),
    ('{"entries": [], "private-key": 1, "private-key": 2}', 'duplicate JSON keys'),
    ('{"entries": [{"id": "private-value", "id": "one", "mentions": []}]}', 'duplicate JSON keys'),
    ('{"entries": [{"id": "one", "mentions": [{"kind": "tools", "name": "private-value", '
     '"name": "React", "evidence": "React is useful."}]}]}', 'duplicate JSON keys'),
    ('```json\n{"entries": [], "private-key": "private-value"}', 'incomplete JSON fencing'),
    ('```json\n{"entries": [], "private-key": "private-value"}\n``', 'incomplete JSON fencing'),
    ('{"entries": [], "private-key": "private-value"}\n```', 'ambiguous extra JSON'),
    ('{"entries": [], "private-key": "private-value",}', 'malformed JSON'),
    ('{"entries": [], "private-key": "private-value"}\n"private-scalar"\nDone.', 'ambiguous extra JSON'),
])
def test_invalid_json_errors_do_not_expose_private_response(extraction, text, message):
    _, _, response, set_response = extraction
    set_response(text)
    with pytest.raises(ValueError, match=f'^Entity response contains {message}$|^Entity response has {message}$') as error:
        parse_response(response)
    assert 'private-' not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None or error.value.__suppress_context__
    with pytest.raises(ValueError):
        entities.enrich()
    assert get_store().records() == {}


def test_token_limited_response_is_not_saved_even_if_json_closes(extraction):
    _, payload, _, set_response = extraction
    set_response(json.dumps(payload), stop_reason='max_tokens')
    with pytest.raises(ValueError):
        entities.enrich()
    assert get_store().records() == {}


def test_collects_text_after_non_text_block(extraction):
    row, payload, response, _ = extraction
    response.content = [SimpleNamespace(type='thinking'),
                        SimpleNamespace(type='text', text=json.dumps(payload)),
                        SimpleNamespace(type='text', text='No other entities.')]
    assert entities.extract_batch([row])['one'][0]['label'] == 'React'


def test_explicit_empty_mentions_are_valid_but_missing_rows_stay_pending(extraction):
    row, _, _, set_response = extraction
    set_response('{"entries": [{"id": "one", "mentions": []}]}')
    assert entities.extract_batch([row]) == {'one': []}
    set_response('{"entries": []}')
    assert entities.enrich()['pending'] == 1
    assert get_store().records() == {}


def test_prompt_requires_full_id_coverage_and_explicit_empty_mentions(extraction, monkeypatch):
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    row, _, response, set_response = extraction
    set_response('{"entries": [{"id": "one", "mentions": []}]}')
    calls = []
    monkeypatch.setattr(BaseApiServiceAnthropic, 'send_messages',
                        lambda self, **kw: calls.append(kw) or response)
    assert entities.enrich()['processed'] == 1
    assert get_store().records()['one']['mentions'] == []
    prompt = calls[0]['system']
    assert 'every input ID exactly once' in prompt
    assert 'mentions: []' in prompt
    assert 'Do not shorten' in prompt


def test_response_diagnostics_count_omitted_and_unknown_ids_privately(extraction):
    row, _, _, set_response = extraction
    set_response('{"entries": [{"id": "PRIVATE-UNKNOWN", "mentions": []}]}')
    assert entities.extract_batch([row]) == {}
    diagnostic = get_store().state('enrichment-response')
    assert diagnostic == dict(supplied=1, returned=1, accepted=0, omitted=1, unknown=1)
    assert 'PRIVATE' not in str(diagnostic)
    assert entities.enrich()['pending'] == 1
    assert get_store().records() == {}


def test_evidence_and_vocabulary_filters_remain_enforced(extraction):
    row, payload, _, set_response = extraction
    payload['entries'][0]['mentions'].extend([
        {'kind': 'unknown', 'name': 'React', 'evidence': 'React is useful.'},
        {'kind': 'tools', 'name': 'Invented', 'evidence': 'React is useful.'},
        {'kind': 'tools', 'name': 'React', 'evidence': 'Invented evidence'},
    ])
    set_response(json.dumps(payload) + '\nDone.')
    assert len(entities.extract_batch([row])['one']) == 1
