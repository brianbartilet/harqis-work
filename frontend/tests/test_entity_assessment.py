"""Bounded assessment and the no-agent runner against the isolated canonical API."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_assessment as assessment, entity_consolidation as runs
from workflows.hfl import entity_consolidation_work as work, entity_executions as executions
from workflows.hfl import entity_matching, entity_merges
from workflows.hfl.entity_store import get_store


@pytest.fixture
def videos(monkeypatch):
    title = "The Real Winners of Korea's AI Stock Crash | AB Explained"
    rows = [dict(id=f'video-{i}', title='Watching Asian Boss', text=f"A YouTube video titled '{title}' is playing full-screen, capture {i}.",
                 source='desktop', date='2026-10-25', tags=[], path='day.md', anchor=str(i), ref='') for i in range(4)]
    monkeypatch.setattr(entities, 'current_entries', lambda: rows.copy())
    monkeypatch.setattr(entity_matching, 'dispatch_pending', lambda: None)
    monkeypatch.setattr(entity_merges, 'flush_audits', lambda: None)
    for row in rows:
        get_store().save(row['id'], entities.entry_hash(row), [entities.mention(row, 'media', title, row['text'], 'model-extracted')])
    return rows


def claimed():
    run = runs.begin()
    work.checkpoint(run['id'])
    executions.start(run['id'], 'test', 40, 900)
    packet = work.claim_work(run['id'], dict(worker_id='test', max_pairs=8))
    return run['id'], packet['claim']['token']


def approve(encoded, ids, model):
    data = json.loads(encoded)
    decisions = {}
    for pair in data['pairs']:
        left, right = (data['entities'][pair[s + '_id']]['activity'][0] for s in ('left', 'right'))
        decisions[ids[pair['id']]] = dict(decision='merge', reason='Same specific video title and YouTube viewing context.',
            contradictions=[], aliases=[], partial_aliases=[], facts=[dict(left_quote=left['text'],
            right_quote=right['text'], explanation='Same specific media work and platform.')])
    return dict(decisions=decisions, contradictions=[], model=model, usage={'input_tokens': 300, 'output_tokens': 200})


def test_exact_media_precedes_fuzzy_people():
    def pair(kind, exact):
        return dict(id=kind, kind=kind, left={'id': 'a', 'related_items': 1},
                    right={'id': 'b', 'related_items': 1}, signals={'exact': exact, 'fuzzy': .9})
    assert runs.pair_priority(pair('media', True)) < runs.pair_priority(pair('people', False))


def test_unprofiled_video_group_assessed_once_and_committed(videos, monkeypatch, authenticated_client):
    calls = []
    monkeypatch.setattr(assessment, 'evaluate', lambda *args: calls.append(args) or approve(*args))
    run_id, token = claimed()
    url = f'/api/hfl/entities/consolidation/{run_id}/claims/{token}/assess'
    result = authenticated_client.post(url, json={}).json()
    assert result['state'] == 'complete' and len(result['decisions']) == 3
    assert authenticated_client.post(url, json={}).json()['cached'] is True
    assert len(calls) == 1
    receipt = runs.merge_group(run_id, {k: result[k] for k in ('anchor_id', 'decisions', 'contradictions')}, token)
    assert receipt['related_items'] == 4
    assert len(entities.entity_index()) == 1
    assert entities.entity_index()[0]['profile']
    execution = executions.close(run_id, 'test', 'exhausted')
    assert len(execution['operation_ids']) == 1
    assert execution['assessment_usage']['input_tokens'] == 300


def test_budget_reservation_prevents_repeated_paid_failure(videos, monkeypatch):
    calls = []
    def fail(*args):
        calls.append(1)
        raise RuntimeError('provider failed')
    monkeypatch.setattr(assessment, 'evaluate', fail)
    run_id, token = claimed()
    with pytest.raises(RuntimeError):
        assessment.assess(run_id, token)
    with pytest.raises(ValueError, match='uncertain'):
        assessment.assess(run_id, token)
    assert calls == [1]
    assert runs.load(run_id)['executions']['test']['assessment_usage']['calls'] == 1


def test_budget_exhaustion_does_not_call_model(videos, monkeypatch):
    run_id, token = claimed()
    run = runs.load(run_id)
    run['executions']['test']['assessment_usage'] = dict(calls=8, input_chars=1, input_tokens=0, output_tokens=0)
    runs.save(run)
    monkeypatch.setattr(assessment, 'evaluate', lambda *args: pytest.fail('budget must prevent call'))
    assert assessment.assess(run_id, token)['state'] == 'budget'
    assert all(p['state'] == 'pending' for p in runs.load(run_id)['pairs'].values())


def test_input_budget_and_unsupported_proposal(videos, monkeypatch):
    run_id, token = claimed()
    monkeypatch.setattr(assessment, 'MAX_INPUT_CHARS', 1)
    assert assessment.assess(run_id, token)['state'] == 'budget'
    monkeypatch.setattr(assessment, 'MAX_INPUT_CHARS', 160000)
    def no_facts(*args):
        result = approve(*args)
        for d in result['decisions'].values():
            d['facts'] = []
        return result
    monkeypatch.setattr(assessment, 'evaluate', no_facts)
    result = assessment.assess(run_id, token)
    assert all(d['decision'] == 'review' for d in result['decisions'].values())
    assert len(entities.entity_index()) == 4


def test_assessment_requires_authentication(videos, authenticated_client):
    run_id, token = claimed()
    authenticated_client.cookies.clear()
    response = authenticated_client.post(f'/api/hfl/entities/consolidation/{run_id}/claims/{token}/assess', json={})
    assert response.status_code in {401, 403}


def test_changed_evidence_rejected_before_spend(videos, monkeypatch):
    run_id, token = claimed()
    live = runs.current_entities()
    live[0]['label'] += ' changed'
    monkeypatch.setattr(runs, 'current_entities', lambda: live)
    monkeypatch.setattr(assessment, 'evaluate', lambda *args: pytest.fail('stale evidence'))
    with pytest.raises(ValueError, match='Evidence changed'):
        assessment.assess(run_id, token)


def test_expired_claim_rejected(videos, monkeypatch):
    run_id, token = claimed()
    run = runs.load(run_id)
    run['claims'][token]['expires_at'] = 0
    runs.save(run)
    with pytest.raises(ValueError, match='live claim'):
        assessment.assess(run_id, token)


def video_pair(url='https://youtu.be/abcdefghijk'):
    def entity(identity):
        return dict(id=identity, kind='media', name='A specific film title', activity=[dict(id=identity,
            text='Watching A specific film title on YouTube at ' + url, corroborating=True)])
    return dict(id='pair', left=entity('a'), right=entity('b'), signals={'exact': True})


def test_video_identifier_fast_path_requires_source_corroboration():
    pair = video_pair()
    assert assessment.deterministic([pair])['model'] == 'deterministic-video-id'
    assert assessment.deterministic([video_pair('')]) is None
    pair['right']['activity'][0]['corroborating'] = False
    assert assessment.deterministic([pair]) is None


def test_explicit_video_id_merges_without_model(videos, monkeypatch):
    for row in videos:
        row['text'] += ' https://youtu.be/abcdefghijk'
        title = "The Real Winners of Korea's AI Stock Crash | AB Explained"
        mention = entities.mention(row, 'media', title, row['text'], 'model-extracted')
        get_store().save(row['id'], entities.entry_hash(row), [mention])
    monkeypatch.setattr(assessment, 'evaluate', lambda *args: pytest.fail('explicit ID does not need model'))
    run_id, token = claimed()
    result = assessment.assess(run_id, token)
    assert result['model'] == 'deterministic-video-id'
    runs.merge_group(run_id, {k: result[k] for k in ('anchor_id', 'decisions', 'contradictions')}, token)
    execution = executions.close(run_id, 'test', 'exhausted')
    assert execution['assessment_usage']['calls'] == 0
    assert len(execution['operation_ids']) == 1


def test_video_identifier_conflicts_never_auto_approve():
    pair = video_pair()
    pair['right']['activity'][0]['text'] += ' https://youtu.be/zyxwvutsrqp'
    assert assessment.deterministic([pair]) is None
    pair['right'] = video_pair('https://youtu.be/zyxwvutsrqp')['right']
    assert assessment.deterministic([pair]) is None


@pytest.mark.parametrize('conflicts', [None, ['Different videos']])
def test_group_conflicts_required_and_veto_merges(monkeypatch, conflicts):
    from apps.antropic import config
    from apps.antropic.references.web import base_api_service
    from workflows.hfl.entity_model_response import EntityModelResponseError
    data = dict(decisions=[dict(id='p1', decision='merge', reason='same', contradictions=[], facts=[])])
    if conflicts is not None:
        data['contradictions'] = conflicts
    response = SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text=json.dumps(data))])
    sdk = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: response))
    sdk.with_options = lambda **kw: sdk
    monkeypatch.setattr(config, 'get_config', lambda _: {})
    monkeypatch.setattr(base_api_service, 'BaseApiServiceAnthropic', lambda _: SimpleNamespace(base_client=sdk))
    if conflicts is None:
        with pytest.raises(EntityModelResponseError):
            assessment.evaluate('{}', {'p1': 'real'}, 'test')
    else:
        assert assessment.evaluate('{}', {'p1': 'real'}, 'test')['decisions']['real']['decision'] == 'review'


def test_runner_merges_four_mentions_and_idempotently_recovers_report(videos, monkeypatch, authenticated_client, tmp_path):
    path = Path(__file__).resolve().parents[2] / 'scripts/agents/hfl/run_entity_consolidation.py'
    spec = importlib.util.spec_from_file_location('batch_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    calls = []
    monkeypatch.setattr(assessment, 'evaluate', lambda *args: calls.append(1) or approve(*args))
    def deliver(report_id):
        report = runs.load(report_id)
        report['delivery'] = dict(hfl={'persisted': True}, url='https://corpus/report', telegram_state='sent')
        runs.save(report)
    monkeypatch.setattr(runs, 'dispatch_reports', deliver)
    api = runner.API(authenticated_client, '/api/hfl/entities', tmp_path / 'journal.json')
    result = runner.run(api, 'batch-test', sleep=lambda _: None)
    assert result['merges'] == 1 and result['tokens_per_merge'] == 500
    assert runner.run(api, 'batch-test', sleep=lambda _: None) == result
    assert calls == [1]
    assert len(entities.entity_index()) == 1
