import importlib.util
import json
import os
import subprocess
import sys
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


def test_artifact_publication_rejects_paths_and_links_local_files(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import httpx
    monkeypatch.setattr(runner, 'spool_root', lambda: tmp_path)
    root = tmp_path / 'workspaces/run'
    root.mkdir(parents=True)
    (root / 'report.md').write_text('# Report', encoding='utf-8')
    sent = []
    def transport(request):
        sent.append(request)
        return httpx.Response(200, json={'url': '/hfl-corpus/agent-bridge/artifacts/run/report.md'})
    with httpx.Client(base_url='https://test/api/hfl-agent/', transport=httpx.MockTransport(transport)) as client:
        bridge = SimpleNamespace(client=client)
        run = {'id': 'run', 'lease_token': 'lease'}
        result = {'summary': '[Report](report.md)', 'artifacts': ['report.md']}
        runner.upload_artifacts(bridge, run, result)
        assert sent[0].content == b'# Report'
        assert sent[0].headers['X-Execution-Lease'] == 'lease'
        assert '?view=true' in result['summary'] and '[Download]' in result['summary']
        for name in ['../outside.md', '/etc/passwd', 'missing.md']:
            with pytest.raises(ValueError):
                runner.upload_artifacts(bridge, run, {'summary': '', 'artifacts': [name]})


def test_discovery_origin_uses_frontend_port(monkeypatch):
    monkeypatch.delenv('HFL_AGENT_BRIDGE_URL', raising=False)
    monkeypatch.setenv('PORT', '8081')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-token')
    client = runner.BridgeClient()
    assert client.client.base_url.port == 8081
    client.client.close()


def test_schedule_reconciliation_is_idempotent_in_isolated_hermes_home(tmp_path):
    try:
        runner.hermes_command()
    except RuntimeError:
        pytest.skip('Local Hermes installation is required for schedule integration.')
    environment = dict(os.environ)
    for key in ('HERMES_PROFILE', 'HERMES_CONFIG', 'HERMES_ENV'):
        environment.pop(key, None)
    environment.update(HERMES_HOME=str(tmp_path / 'hermes'), HERMES_TIMEZONE='Asia/Singapore', PYTHONIOENCODING='utf-8')
    script = Path(runner.__file__).with_name('setup_agent_bridge.py')
    def invoke(*args):
        result = subprocess.run([sys.executable, str(script), *args], env=environment, text=True, encoding='utf-8', capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert invoke()['existing_jobs'] == 0
    assert not (tmp_path / 'hermes/scripts/hfl_agent_bridge_daily.py').exists()
    first = invoke('--apply')
    second = invoke('--apply')
    assert first['job_id'] == second['job_id']
    assert Path(first['script']).is_relative_to(tmp_path)
    assert invoke()['existing_jobs'] == 1
    jobs = json.loads((tmp_path / 'hermes/cron/jobs.json').read_text(encoding='utf-8'))
    rows = jobs['jobs'] if isinstance(jobs, dict) else jobs
    assert len(rows) == 1
    assert rows[0]['no_agent'] is True
    assert rows[0]['deliver'] == 'local'
