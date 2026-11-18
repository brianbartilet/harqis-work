"""Opt-in real API checks; decision smoke sends synthetic data and may incur cost."""
import os
import pytest
from hamcrest import assert_that, instance_of

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv('TYPESAFE_LIVE_TESTS') != '1', reason='Set TYPESAFE_LIVE_TESTS=1 for real API calls.')]


@pytest.mark.smoke
def test_models():
    from apps.typesafe.config import CONFIG
    from apps.typesafe.references.web.api.system_one import ApiServiceTypeSafeDecisions
    assert_that(ApiServiceTypeSafeDecisions(CONFIG).list_models(), instance_of(list))


@pytest.mark.sanity
def test_synthetic_decision(tmp_path, monkeypatch):
    from apps.typesafe.config import CONFIG
    from apps.typesafe.references.web.api.system_one import ApiServiceTypeSafeDecisions
    monkeypatch.setenv('TYPESAFE_RECEIPTS_DB', str(tmp_path / 'receipts.sqlite3'))
    result = ApiServiceTypeSafeDecisions(CONFIG).analyze_decision('action_triage_v1', {
        'action': {'title': 'Fix failing unit test', 'description': 'Investigate a Python assertion failure.'},
        'candidate_agents': [{'id': 'code', 'name': 'Coder', 'capabilities': ['Debug Python tests']}]})
    assert result['status'] in {'recommendation', 'needs_review'}
    assert result['execution_authorized'] is False
