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


def test_board_result_normalizes_plan_steps_and_evidence_objects():
    result = {'plan': ['Inspect board', 'Propose branches'], 'summary': 'Seven proposals',
              'state': 'succeeded', 'complete': True,
              'evidence': [{'reference': 'mindmap:map-1', 'detail': 'Board purpose'},
                           {'id': 'draft:1', 'relevance': 'Starting thought'}, {'ref': 'goal:1'}],
              'ideas': [{'title': 'Define scope', 'parents': ['draft:1']}]}
    parsed = runner.parse_result(json.dumps(result), board_planning=True)
    assert parsed['plan'] == '- Inspect board\n- Propose branches'
    assert parsed['evidence'] == ['mindmap:map-1', 'draft:1', 'goal:1']
    assert parsed['ideas'] == result['ideas']
    with pytest.raises(ValueError):
        runner.parse_result(json.dumps(result))
    for fields in ({'plan': ['Good', 42]}, {'evidence': [{'detail': 'No reference'}]}, {'evidence': []}):
        with pytest.raises(ValueError):
            runner.parse_result(json.dumps({**result, **fields}), board_planning=True)


def test_worker_restores_verified_inputs_separately_from_outputs(tmp_path, monkeypatch):
    import hashlib
    import httpx
    from types import SimpleNamespace
    monkeypatch.setattr(runner, 'spool_root', lambda: tmp_path)
    content = b'Original briefing'
    item = {'id': 'a' * 32, 'filename': 'a' * 32 + '.md', 'name': 'Brief.md',
            'digest': hashlib.sha256(content).hexdigest(), 'size': len(content)}
    run = {'id': 'run', 'lease_token': 'lease', 'snapshot': {'runtime_prompt': 'Read inputs', 'source': {'attachments': [item]}}}
    def transport(request):
        assert request.headers['X-Execution-Lease'] == 'lease'
        assert request.url.path == '/runs/run/inputs/' + item['id']
        return httpx.Response(200, content=content)
    with httpx.Client(base_url='https://worker.test/', transport=httpx.MockTransport(transport)) as client:
        runner.restore_input_attachments(SimpleNamespace(client=client), run)
        workspace = tmp_path / 'workspaces/run'
        assert (workspace / 'inputs' / item['filename']).read_bytes() == content
        prompt = json.loads(runner.execution_prompt(run, workspace).split('\n\n', 1)[1])
        assert prompt['input_directory'] == str((workspace / 'inputs').resolve())
        item['digest'] = '0' * 64
        with pytest.raises(ValueError, match='integrity'):
            runner.restore_input_attachments(SimpleNamespace(client=client), run)
        item['filename'] = '../escape.md'
        with pytest.raises(ValueError, match='filename'):
            runner.restore_input_attachments(SimpleNamespace(client=client), run)


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


@pytest.mark.parametrize('mode,restricted', [('trusted', False), ('restricted', True)])
def test_hermes_program_loads_profile_and_mode(tmp_path, mode, restricted):
    package = tmp_path / 'hermes_cli'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'config.py').write_text("def load_config_readonly(): return {'model': {'default': 'profile-model', 'provider': 'profile-provider'}, 'mcp_servers': {'harqis': {}}}")
    (package / 'profiles.py').write_text("from pathlib import Path\ndef get_profile_dir(name): return Path(__file__).parent")
    (tmp_path / 'cli.py').write_text("import json, os\ndef main(**kwargs):\n print('CALL=' + json.dumps(kwargs))\n print('SAFE=' + str(os.environ.get('HERMES_SAFE_MODE')))\n")
    environment = dict(os.environ)
    environment.update(HFL_AGENT_HERMES_ROOT=str(tmp_path), HFL_AGENT_EXECUTION_SETTINGS=json.dumps({'agent_mode': mode, 'hermes_profile': 'research', 'agent_max_turns': 45}), HERMES_SAFE_MODE='1')
    environment.pop('HFL_AGENT_CAPABILITY_CHECK', None)
    result = subprocess.run([sys.executable, '-c', runner.HERMES_PROGRAM], input='Task', text=True, capture_output=True, env=environment, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    call = json.loads(next(line[5:] for line in result.stdout.splitlines() if line.startswith('CALL=')))
    assert call['ignore_user_config'] is restricted
    assert call['ignore_rules'] is restricted
    assert call['max_turns'] == 45
    assert call['toolsets'] == ('web,terminal,file,code_execution' if restricted else None)
    runtime = json.loads(next(line.split('=', 1)[1] for line in result.stdout.splitlines() if line.startswith('HFL_BRIDGE_RUNTIME=')))
    assert runtime['profile'] == 'research'
    assert runtime['configured_mcp_servers'] == ([] if restricted else ['harqis'])


def test_known_credentials_redacted_from_diagnostics_and_output():
    assert runner.redact_credentials('token secret-value and result', {'API_TOKEN': 'secret-value', 'PATH': 'result'}) == 'token [REDACTED] and result'


def test_continuation_restores_verified_files_and_preserves_operation_scope(tmp_path, monkeypatch):
    import hashlib
    import httpx
    from types import SimpleNamespace
    monkeypatch.setattr(runner, 'spool_root', lambda: tmp_path)
    content = b'# Existing report'
    artifact = {'name': 'report.md', 'digest': hashlib.sha256(content).hexdigest(), 'size': len(content)}
    run = {'id': 'second', 'request_key': 'new-attempt', 'lease_token': 'lease', 'snapshot': {
        'runtime_prompt': 'Continue the task.', 'operation_scope': 'original-operation',
        'continuation': {'reply': 'Email the existing file.', 'history': [{'result': {'summary': 'File ready'}}], 'artifacts': [artifact]}}}
    def transport(request):
        assert request.headers['X-Execution-Lease'] == 'lease'
        assert request.url.path.endswith('/runs/second/prior-artifacts/report.md')
        return httpx.Response(200, content=content)
    with httpx.Client(base_url='https://bridge.test/api/hfl-agent/', transport=httpx.MockTransport(transport)) as client:
        runner.restore_prior_artifacts(SimpleNamespace(client=client), run)
        workspace = tmp_path / 'workspaces/second'
        assert (workspace / 'report.md').read_bytes() == content
        prompt = json.loads(runner.execution_prompt(run, workspace).split('\n\n', 1)[1])
        assert prompt['operation_scope'] == 'original-operation'
        assert prompt['continuation']['reply'] == 'Email the existing file.'
        artifact['digest'] = '0' * 64
        with pytest.raises(ValueError, match='integrity'):
            runner.restore_prior_artifacts(SimpleNamespace(client=client), run)
        artifact['name'] = '../escape.md'
        with pytest.raises(ValueError, match='filename'):
            runner.restore_prior_artifacts(SimpleNamespace(client=client), run)


def test_matrix_result_validation():
    result = {'plan':'Prioritize important work', 'summary':'Plan ready', 'evidence':['actionable:1'], 'state':'succeeded', 'complete':True,
              'matrix':'Q2', 'matrix_confidence':'medium', 'matrix_reason':'Durable improvement without a deadline'}
    assert runner.parse_result(json.dumps(result)) == result
    for fields in [{'matrix':'Q9'}, {'matrix_confidence':'certain'}, {'matrix_reason':[]}]:
        with pytest.raises(ValueError):
            runner.parse_result(json.dumps({**result, **fields}))
