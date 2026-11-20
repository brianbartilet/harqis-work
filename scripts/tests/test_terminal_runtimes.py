import json
from types import SimpleNamespace

from scripts.agents.hfl import terminal_runtimes as runtimes


def test_native_launch_preserves_approval_and_does_not_submit_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(runtimes, 'executable', lambda name: name)
    settings = {'initial_context': {'prompt': 'DO NOT AUTOMATICALLY EXECUTE'}}
    workspace = SimpleNamespace(path=tmp_path / 'checkout')
    for name in ('codex', 'claude'):
        command, native_id = runtimes.native_command(name, settings, workspace, tmp_path, 'a' * 32, '')
        assert 'DO NOT AUTOMATICALLY EXECUTE' not in ' '.join(command)
        assert not any('skip-permissions' in part or 'bypass' in part for part in command)
        assert json.loads((tmp_path / 'action-context.json').read_text()) == settings['initial_context']
        if name == 'codex':
            assert command[command.index('--ask-for-approval') + 1] == 'on-request'
        else:
            assert native_id == 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def test_capabilities_do_not_publish_auth_output(monkeypatch):
    monkeypatch.setattr(runtimes, 'executable', lambda name: name)
    monkeypatch.setattr(runtimes.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='PRIVATE'))
    def absent():
        raise RuntimeError('PRIVATE')
    result = runtimes.capabilities(SimpleNamespace(hermes_command=absent))
    assert all(not item['available'] for item in result)
    assert 'PRIVATE' not in json.dumps(result)


def test_windows_codex_uses_nearest_installed_dependency(tmp_path, monkeypatch):
    shim = tmp_path / 'codex.cmd'
    shim.touch()
    package = tmp_path / 'node_modules/@openai'
    sibling = package / 'codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
    nested = package / 'codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
    for path in (sibling, nested):
        path.parent.mkdir(parents=True)
        path.touch()
    monkeypatch.setattr(runtimes.shutil, 'which', lambda _: str(shim))
    assert runtimes.executable('codex') == str(nested)
