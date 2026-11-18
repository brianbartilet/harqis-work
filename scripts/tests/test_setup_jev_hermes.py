import os
import yaml
import pytest
from scripts.setup_jev_hermes import prepare


@pytest.fixture
def paths(tmp_path):
    root = tmp_path / 'repo'
    executable = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    executable.parent.mkdir(parents=True)
    executable.touch()
    profile = tmp_path / 'jev'
    profile.mkdir()
    (profile / 'config.yaml').write_text('model: existing\nmcp_servers:\n  existing: {command: example}\n', encoding='utf-8')
    return root, profile


def test_dry_run_and_idempotent_apply(paths):
    root, profile = paths
    before = (profile / 'config.yaml').read_bytes()
    assert prepare(profile, root=root)['mode'] == 'dry-run'
    assert list(profile.iterdir()) == [profile / 'config.yaml']
    assert prepare(profile, root=root, apply=True)['changed']
    config = yaml.safe_load((profile / 'config.yaml').read_text())
    assert config['model'] == 'existing'
    assert config['mcp_servers']['existing'] == {'command': 'example'}
    assert config['mcp_servers']['harqis_typesafe']['env']['MCP_ENABLED_APPS'] == 'typesafe'
    assert (profile / 'config.yaml.before-jev').read_bytes() == before
    assert (profile / 'skills/jev-action-triage/SKILL.md').is_file()
    assert not prepare(profile, root=root, apply=True)['changed']


def test_conflicting_connector_preserved(paths):
    root, profile = paths
    path = profile / 'config.yaml'
    path.write_text('mcp_servers:\n  harqis_typesafe: {command: custom}\n')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='differs'):
        prepare(profile, root=root, apply=True)
    assert path.read_bytes() == before


def test_modified_skill_preserved(paths):
    root, profile = paths
    prepare(profile, root=root, apply=True)
    skill = profile / 'skills/jev-action-triage/SKILL.md'
    skill.write_text('custom')
    with pytest.raises(ValueError, match='differs'):
        prepare(profile, root=root, apply=True)
    assert skill.read_text() == 'custom'


def test_missing_profile_is_not_created(tmp_path):
    with pytest.raises(ValueError, match='dedicated Hermes profile'):
        prepare(tmp_path / 'missing')
    assert not (tmp_path / 'missing').exists()


def test_mcp_bootstrap_preserves_explicit_profile_receipts(monkeypatch):
    from scripts import launch
    monkeypatch.setenv('TYPESAFE_RECEIPTS_DB', '/profile/receipts.sqlite3')
    monkeypatch.setenv('MCP_ENABLED_APPS', 'typesafe')
    def host_environment():
        os.environ['TYPESAFE_RECEIPTS_DB'] = '/shared/receipts.sqlite3'
        os.environ['MCP_ENABLED_APPS'] = 'trello'
    monkeypatch.setattr(launch, 'setup_env', host_environment)
    launch.setup_mcp_env()
    assert os.environ['TYPESAFE_RECEIPTS_DB'] == '/profile/receipts.sqlite3'
    assert os.environ['MCP_ENABLED_APPS'] == 'typesafe'
