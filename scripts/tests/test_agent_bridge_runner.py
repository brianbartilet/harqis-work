import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('agent_bridge_runner', Path(__file__).resolve().parents[1] / 'agents/hfl/agent_bridge_runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_parse_result_accepts_cli_session_footer_but_rejects_ambiguous_results():
    result = {'plan': 'Read sources', 'summary': 'A draft', 'evidence': ['pin:1'], 'state': 'succeeded', 'complete': True}
    encoded = json.dumps(result)
    assert runner.parse_result('```json\n' + encoded + '\n```\nSession: abc') == result
    with pytest.raises(ValueError):
        runner.parse_result(encoded + '\n' + encoded)
    with pytest.raises(ValueError):
        runner.parse_result(json.dumps({**result, 'evidence': []}))
    with pytest.raises(ValueError):
        runner.parse_result(json.dumps({**result, 'complete': 'yes'}))


def test_worker_rejects_remote_plaintext_and_missing_token(monkeypatch):
    monkeypatch.setenv('HFL_AGENT_BRIDGE_URL', 'http://remote.example')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-token')
    with pytest.raises(ValueError, match='HTTPS'):
        runner.BridgeClient()
    monkeypatch.setenv('HFL_AGENT_BRIDGE_URL', 'http://127.0.0.1:8000')
    monkeypatch.delenv('HFL_AGENT_BRIDGE_TOKEN')
    with pytest.raises(ValueError, match='TOKEN'):
        runner.BridgeClient()
