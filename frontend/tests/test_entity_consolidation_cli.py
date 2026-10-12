"""Exercise the shipped CLI against isolated real API routes, not production."""
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest

from test_entity_consolidation import alias_group, corpus  # noqa: F401


@pytest.fixture
def helper(monkeypatch, authenticated_client):
    from scripts import deploy
    path = Path(__file__).resolve().parents[2] / '.agents/skills/auto-merge-entities/scripts/consolidate.py'
    spec = importlib.util.spec_from_file_location('consolidation_cli', path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(deploy, 'load_env_into_os', lambda: None)
    monkeypatch.setattr(deploy, 'load_machine_config', lambda _: {})
    monkeypatch.setattr(deploy, 'machine_env_vars', lambda _: {})
    monkeypatch.setenv('HFL_CORPUS_API_URL', 'http://testserver')
    monkeypatch.setenv('HFL_CORPUS_API_TOKEN', 'test-token')
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return authenticated_client
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(httpx, 'Client', Client)
    def invoke(*args):
        monkeypatch.setattr(sys, 'argv', ['consolidate.py', *args])
        return cli.main()
    return invoke


def test_cli_compact_status_and_atomic_group(helper, alias_group, tmp_path, capsys):
    run, payload = alias_group
    assert helper('status', run['id'], '--compact', '--limit', '2') == 0
    result = json.loads(capsys.readouterr().out)
    assert result['format'] == 'anchor-packets-v1' and len(result['pairs']) == 2
    path = tmp_path / 'group.json'
    path.write_text(json.dumps(payload))
    assert helper('group', run['id'], '--file', str(path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'merged' and result['related_items'] == 3
    assert helper('group', run['id'], '--file', str(path)) == 0
    assert json.loads(capsys.readouterr().out) == result


def test_cli_compact_rejects_old_server_format(helper, alias_group, monkeypatch, capsys):
    from workflows.hfl import entity_consolidation
    run, _ = alias_group
    monkeypatch.setattr(entity_consolidation, 'compact_view', lambda result: result)
    assert helper('status', run['id'], '--compact') == 1
    assert 'unsupported' in json.loads(capsys.readouterr().out)['error']


def test_cli_non_json_error_is_safe(helper, alias_group, monkeypatch, authenticated_client, capsys):
    run, _ = alias_group
    monkeypatch.setattr(authenticated_client, 'get', lambda *a, **k: httpx.Response(502, text='private proxy body'))
    assert helper('status', run['id']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 502
    assert 'private proxy body' not in str(result)
