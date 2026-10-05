from types import SimpleNamespace

import pytest

from workflows.hfl import timeline


def response(text, stop_reason='end_turn'):
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type='text', text=text)])


@pytest.fixture
def model(monkeypatch):
    from apps.hfl_corpus.references.web.api.ideas import ApiServiceHflCorpusIdeas
    monkeypatch.setattr(ApiServiceHflCorpusIdeas, 'get_board_context', lambda self: {'boards': []})
    from apps.antropic import config
    from apps.antropic.references.web import base_api_service
    calls, replies = [], []

    class Client:
        def __init__(self, config):
            pass

        def send_message(self, **kwargs):
            calls.append(kwargs)
            result = replies.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(config, 'get_config', lambda name: None)
    monkeypatch.setattr(base_api_service, 'BaseApiServiceAnthropic', Client)
    return calls, replies


@pytest.mark.parametrize('first', [response('{"findings":[]}', 'max_tokens'),
                                  response('{"findings":['), response('{"wrong":[]}')])
def test_synthesis_retries_unusable_output_once(model, first):
    calls, replies = model
    replies.extend([first, response('{"findings":[]}')])
    assert timeline.synthesize([], start='2026-09-26', end='2026-09-26') == {'findings': []}
    assert [call['max_tokens'] for call in calls] == [4096, 8192]
    assert calls[0]['prompt'] == calls[1]['prompt']


def test_complete_response_does_not_retry_and_ignores_nontext_blocks(model):
    calls, replies = model
    result = response('{"findings":[]}')
    result.content.insert(0, SimpleNamespace(type='thinking'))
    replies.append(result)
    assert timeline.synthesize([], start='2026-09-26', end='2026-09-26') == {'findings': []}
    assert len(calls) == 1


def test_exhausted_output_limit_is_explicit_and_bounded(model):
    calls, replies = model
    replies.extend([response('private incomplete content', 'max_tokens')] * 2)
    with pytest.raises(timeline.TimelineModelError, match='output limit') as caught:
        timeline.synthesize([], start='2026-09-26', end='2026-09-26')
    assert len(calls) == 2
    assert 'private' not in str(caught.value)


def test_transport_errors_are_not_retried_as_json_errors(model):
    calls, replies = model
    replies.append(ConnectionError('unavailable'))
    with pytest.raises(ConnectionError):
        timeline.synthesize([], start='2026-09-26', end='2026-09-26')
    assert len(calls) == 1


def test_duplicate_review_uses_same_truncation_recovery(model):
    calls, replies = model
    replies.extend([response('{"decisions":[', 'max_tokens'), response('{"decisions":[]}')])
    assert timeline.review_actions([], {'actions': [], 'dismissed_ideas': []}, []) == []
    assert len(calls) == 2


def test_celery_records_failure_after_elasticsearch_logs_it(monkeypatch):
    from core.apps.es_logging.app import elasticsearch
    from workflows.hfl.tasks import timeline_suggestions as task
    logged = []
    monkeypatch.setattr(elasticsearch, '_ES_CONFIGURED', True)
    monkeypatch.setattr(elasticsearch, 'get_index_data', lambda *args, **kwargs: [])
    monkeypatch.setattr(elasticsearch, 'post', lambda **kwargs: logged.append(kwargs['json_dump']))
    monkeypatch.setattr(task, 'FollowUpStore', lambda path: SimpleNamespace(receipts=lambda **kwargs: []))

    def fail(*args, **kwargs):
        raise timeline.TimelineModelError('The model response reached its output limit.')

    monkeypatch.setattr(task, 'explore_period', fail)
    result = task.generate_timeline_suggestions.apply(throw=False)
    assert result.state == 'FAILURE'
    assert isinstance(result.result, timeline.TimelineModelError)
    assert logged[0]['failed'] == 1
    assert logged[0]['passed'] == 0
    assert logged[0]['name'] == 'workflows.hfl.tasks.timeline_suggestions.generate_timeline_suggestions'


def test_model_failure_preserves_cached_suggestions_and_exposes_safe_reason(tmp_path):
    from workflows.hfl.timeline_store import FollowUpStore
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    day = '2026-09-26'
    old_run = store.claim_period(day, day)
    store.start_period(day, day, old_run)
    suggestion = {'category': 'recommendations', 'title': 'Cached idea',
                  'evidence': [{'entry_id': 'old'}], 'status': 'uncertain'}
    store.save_suggestions(day, day, old_run, [suggestion], {})
    cached = store.suggestions(day, day)
    run = store.claim_period(day, day, force=True)

    def fail(*args):
        raise timeline.TimelineModelError('The model response reached its output limit.')

    with pytest.raises(timeline.TimelineModelError):
        timeline.explore_period(day, day, run_id=run, store=store, collect=fail)
    assert store.suggestions(day, day) == cached
    saved = store.run_for(day, day)
    assert saved['state'] == 'failed'
    assert 'output limit' in saved['result']['message']
