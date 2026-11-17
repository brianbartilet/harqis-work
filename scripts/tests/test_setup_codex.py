from pathlib import Path
from unittest.mock import Mock
import pytest
from scripts import setup_codex as setup


@pytest.fixture
def clean_host(monkeypatch, tmp_path):
    monkeypatch.delenv('HARQIS_CODEX_BINARY', raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(setup.shutil, 'which', lambda name: None)
    return tmp_path


def binary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'fake binary')
    path.chmod(0o755)
    return str(path)


@pytest.mark.parametrize('package', ['app-server-daemon', 'standalone'])
def test_managed_installation_reused_without_network(clean_host, monkeypatch, package):
    name = 'codex.exe' if setup.os.name == 'nt' else 'codex'
    expected = binary(clean_host / '.codex/packages' / package / 'current/bin' / name)
    network = Mock(side_effect=AssertionError('must not download'))
    monkeypatch.setattr(setup.urllib.request, 'urlopen', network)
    assert setup.install_if_missing(True) == expected
    network.assert_not_called()


def test_invalid_override_does_not_install(clean_host, monkeypatch):
    monkeypatch.setenv('HARQIS_CODEX_BINARY', str(clean_host/'missing'))
    with pytest.raises(RuntimeError, match='correct the host machine variable'):
        setup.install_if_missing(True)


def test_missing_is_read_only_by_default(clean_host, monkeypatch):
    download = Mock()
    monkeypatch.setattr(setup.urllib.request, 'urlopen', download)
    with pytest.raises(RuntimeError, match='--install'):
        setup.install_if_missing()
    download.assert_not_called()


def test_install_missing_and_rediscover(clean_host, monkeypatch):
    monkeypatch.setattr(setup.sys, 'platform', 'darwin')
    monkeypatch.setattr(setup.shutil, 'which', lambda name: '/bin/sh' if name == 'sh' else None)
    response = Mock()
    response.read.return_value = b'#!/bin/sh\nexit 0\n'
    context = Mock(__enter__=Mock(return_value=response), __exit__=Mock(return_value=False))
    monkeypatch.setattr(setup.urllib.request, 'urlopen', Mock(return_value=context))
    name = 'codex.exe' if setup.os.name == 'nt' else 'codex'
    dest = clean_host / '.codex/packages/standalone/current/bin' / name
    run = Mock(side_effect=lambda *a, **kw: binary(dest))
    monkeypatch.setattr(setup.subprocess, 'run', run)
    assert setup.install_if_missing(True) == str(dest)
    assert run.call_args.args[0][0] == '/bin/sh'


def test_failed_install_not_reported_ready(clean_host, monkeypatch):
    monkeypatch.setattr(setup.sys, 'platform', 'darwin')
    monkeypatch.setattr(setup.shutil, 'which', lambda name: '/bin/sh' if name == 'sh' else None)
    response = Mock()
    response.read.return_value = b'<html>error</html>'
    context = Mock(__enter__=Mock(return_value=response), __exit__=Mock(return_value=False))
    monkeypatch.setattr(setup.urllib.request, 'urlopen', Mock(return_value=context))
    run = Mock()
    monkeypatch.setattr(setup.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='nothing executed'):
        setup.install_if_missing(True)
    run.assert_not_called()
