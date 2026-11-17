"""Offline contract tests; no API keys or external requests required."""
import copy
import json
import sqlite3

import httpx
import pytest

from apps.typesafe.config import CONFIG
from apps.typesafe.references.dto.system_one import TypeSafeError
from apps.typesafe.references.web.api.system_one import ApiServiceTypeSafeDecisions
from apps.typesafe.templates import build


@pytest.fixture
def state():
    return {'action': {'title': 'Private title', 'description': 'Private incident details'},
            'candidate_agents': [
                {'id': 'coder', 'name': 'Private Coder', 'capabilities': ['Fix Python']},
                {'id': 'writer', 'name': 'Private Writer', 'capabilities': ['Write copy']}]}


def response(state):
    questions, _ = build('action_triage_v1', state)
    keys = list(questions['agent']['criteria'])
    return {'model': 'jev-test-version', 'usage': {'input_tokens': 200, 'output_tokens': 50}, 'answers': {
        'suitable': {'type': 'noul', 'noul': .95},
        'missing': {'type': 'noul', 'noul': .05},
        'agent': {'type': 'choice', 'choice': keys[0], 'probabilities': {keys[0]: .9, keys[1]: .1}, 'confidence': .8},
        'urgency': {'type': 'score', 'score': 1.7, 'probabilities': {'0': .1, '1': .1, '2': .8}, 'confidence': .5}}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / 'decisions.sqlite3'
    monkeypatch.setenv('TYPESAFE_RECEIPTS_DB', str(path))
    return path


def service(handler, sleep=lambda _: None):
    config = copy.deepcopy(CONFIG)
    config.app_data['api_key'] = 'synthetic-test-key'
    return ApiServiceTypeSafeDecisions(config, transport=httpx.MockTransport(handler), sleep=sleep)


def test_recommendation_request_and_private_receipt(state, db):
    def handler(request):
        assert str(request.url) == 'https://api.typesafe.ai/v1/systemone'
        assert request.headers['Authorization'] == 'Bearer synthetic-test-key'
        payload = json.loads(request.content)
        assert payload['state'] == state
        assert set(payload['questions']) == {'agent', 'urgency', 'suitable', 'missing'}
        return httpx.Response(200, json=response(state))
    result = service(handler).analyze_decision('action_triage_v1', state)
    assert result['status'] == 'recommendation'
    assert result['recommended_agent_id'] == 'coder'
    assert result['execution_authorized'] is False
    with sqlite3.connect(db) as connection:
        payload = connection.execute('SELECT payload FROM decisions').fetchone()[0]
    assert 'Private' not in payload and 'synthetic-test-key' not in payload
    receipt = json.loads(payload)
    assert receipt['answers']['agent']['choice'] == 'coder'
    assert receipt['receipt_id'] == result['receipt_id']


@pytest.mark.parametrize('field,value,reason', [
    ('suitable', .2, 'no_clear_suitable_candidate'), ('missing', .6, 'missing_information')])
def test_review_outcomes(state, db, field, value, reason):
    raw = response(state)
    raw['answers'][field]['noul'] = value
    result = service(lambda _: httpx.Response(200, json=raw)).analyze_decision('action_triage_v1', state)
    assert result['status'] == 'needs_review'
    assert result['recommended_agent_id'] is None
    assert reason in result['reason_codes']


def test_ambiguous_choice(state, db):
    raw = response(state)
    raw['answers']['agent']['probabilities'] = dict(zip(raw['answers']['agent']['probabilities'], [.55, .45]))
    result = service(lambda _: httpx.Response(200, json=raw)).analyze_decision('action_triage_v1', state)
    assert result['status'] == 'needs_review'
    assert result['reason_codes'] == ['ambiguous_choice']


@pytest.mark.parametrize('mutation', ['missing_answer', 'wrong_type', 'unknown_choice', 'negative', 'sum', 'score', 'usage', 'extra'])
def test_invalid_provider_answers_are_errors(state, db, mutation):
    raw = response(state)
    if mutation == 'missing_answer': del raw['answers']['missing']
    if mutation == 'wrong_type': raw['answers']['missing']['type'] = 'choice'
    if mutation == 'unknown_choice': raw['answers']['agent']['choice'] = 'intruder'
    if mutation == 'negative': raw['answers']['missing']['noul'] = -1
    if mutation == 'sum': raw['answers']['urgency']['probabilities']['0'] = .9
    if mutation == 'score': raw['answers']['urgency']['score'] = 0
    if mutation == 'usage': raw['usage']['input_tokens'] = True
    if mutation == 'extra': raw['answers']['extra'] = {'type': 'noul', 'noul': 1}
    result = service(lambda _: httpx.Response(200, json=raw)).analyze_decision('action_triage_v1', state)
    assert result['status'] == 'error'
    assert 'recommended_agent_id' not in result


@pytest.mark.parametrize('status,attempts', [(401, 1), (403, 1), (422, 1), (302, 1), (429, 3), (503, 3)])
def test_http_errors_sanitized_and_bounded(state, db, status, attempts):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='SECRET provider echoed state', headers={'Location': 'https://other.example'})
    result = service(handler).analyze_decision('action_triage_v1', state)
    assert result['status'] == 'error'
    assert 'SECRET' not in json.dumps(result)
    assert len(calls) == attempts


def test_retry_recovers(state, db):
    calls, sleeps = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json=response(state))
    assert service(handler, sleeps.append).analyze_decision('action_triage_v1', state)['status'] == 'recommendation'
    assert sleeps == [1, 2]


def test_timeout_is_not_retried(state, db):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('SECRET')
    result = service(handler).analyze_decision('action_triage_v1', state)
    assert result['status'] == 'error' and len(calls) == 1
    assert 'SECRET' not in result['error']


@pytest.mark.parametrize('body', [b'not JSON', b'x' * 256001, b'{"model": null}'], ids=['invalid-json', 'oversized', 'invalid-schema'])
def test_bad_body(state, db, body):
    result = service(lambda _: httpx.Response(200, content=body)).analyze_decision('action_triage_v1', state)
    assert result['status'] == 'error'


@pytest.mark.parametrize('mutation', ['empty', 'duplicate', 'extra', 'oversized', 'bad_id'])
def test_invalid_state_never_calls_api(state, db, mutation):
    if mutation == 'empty': state['candidate_agents'] = []
    if mutation == 'duplicate': state['candidate_agents'][1]['id'] = 'coder'
    if mutation == 'extra': state['action']['secret'] = 'do not forward'
    if mutation == 'oversized': state['action']['description'] = 'x' * 16001
    if mutation == 'bad_id': state['candidate_agents'][0]['id'] = '../escape'
    with pytest.raises(ValueError):
        service(lambda _: pytest.fail('Unexpected network call')).analyze_decision('action_triage_v1', state)
    assert not db.exists()


def test_unknown_template(state, db):
    with pytest.raises(ValueError):
        service(lambda _: pytest.fail('Unexpected network call')).analyze_decision('unknown', state)


def test_missing_credential():
    config = copy.deepcopy(CONFIG)
    config.app_data['api_key'] = '${TYPESAFE_API_KEY}'
    with pytest.raises(TypeSafeError, match='Configure TYPESAFE_API_KEY'):
        ApiServiceTypeSafeDecisions(config)


def test_receipt_failure_blocks_success(state, db, monkeypatch):
    monkeypatch.setattr('apps.typesafe.receipts.ReceiptStore.save', lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(TypeSafeError, match='receipt could not be persisted'):
        service(lambda _: httpx.Response(200, json=response(state))).analyze_decision('action_triage_v1', state)


def test_model_discovery():
    models = [{'name': 'jev-test', 'description': 'Test model', 'release_date': '2026-11-18'}]
    def handler(request):
        assert request.method == 'GET' and request.url.path == '/v1/models'
        return httpx.Response(200, json={'models': models})
    assert service(handler).list_models() == models


def test_cli_and_mcp_discovery():
    from tools.cli import run
    payload = json.dumps(run(['commands', 'typesafe']))
    assert 'list_typesafe_models' in payload and 'analyze_typesafe_decision' in payload
    schema = json.dumps(run(['schema', 'typesafe', 'analyze_typesafe_decision']))
    assert 'template' in schema and 'state' in schema
