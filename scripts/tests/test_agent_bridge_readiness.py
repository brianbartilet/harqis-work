"""Readiness must never consume/reconcile production work."""
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('readiness_runner', ROOT / 'scripts/agents/hfl/agent_bridge_runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_check_only_requests_readiness(monkeypatch, tmp_path, capsys):
    requests = []
    def respond(request):
        requests.append((request.method, request.url.path))
        assert request.method == 'GET'
        assert request.url.path == '/api/hfl-agent/ready'
        return httpx.Response(200, json={'status': 'ok', 'service': 'hfl-agent-bridge'})
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-secret')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_URL', 'http://127.0.0.1:8081')
    client = runner.BridgeClient()
    client.client.close()
    client.client = httpx.Client(base_url='http://127.0.0.1:8081/api/hfl-agent/', transport=httpx.MockTransport(respond))
    monkeypatch.setattr(runner, 'BridgeClient', lambda: client)
    monkeypatch.setattr(runner, 'bootstrap', lambda: None)
    monkeypatch.setattr(runner, 'hermes_command', lambda *args: ([sys.executable, '-c', 'pass'], tmp_path))
    monkeypatch.setattr(sys, 'argv', ['bridge', '--check'])
    runner.main()
    assert requests == [('GET', '/api/hfl-agent/ready')]
    assert client.client.is_closed
    assert 'available' in capsys.readouterr().out


@pytest.mark.parametrize('status,payload', [(401, {}), (503, {}), (404, {}), (302, {}), (200, []), (200, {}), (200, {'status': 'ok', 'service': 'other'})])
def test_readiness_fails_closed(monkeypatch, status, payload):
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-secret')
    client = runner.BridgeClient()
    client.client.close()
    client.client = httpx.Client(base_url='http://localhost/api/hfl-agent/', transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        client.check_ready()
    client.client.close()


def test_readiness_timeout_is_bounded(monkeypatch):
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-secret')
    def respond(request):
        assert max(request.extensions['timeout'].values()) <= 10
        raise httpx.ReadTimeout('test timeout')
    client = runner.BridgeClient()
    client.client.close()
    client.client = httpx.Client(base_url='http://localhost/api/hfl-agent/', transport=httpx.MockTransport(respond))
    with pytest.raises(httpx.ReadTimeout):
        client.check_ready()
    client.client.close()
