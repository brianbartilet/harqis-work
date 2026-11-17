"""Install the Jev skill and scoped MCP entry into an existing Hermes profile.

Usage: python scripts/setup_jev_hermes.py --profile-home /path/to/profile [--apply]
Dry-run by default. Does not install Hermes, fetch third-party code, authenticate,
start a gateway, change models, schedule work, or register a Fleet agent.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.agents/skills/jev-action-triage/SKILL.md'


def prepare(profile_home, *, apply=False, root=ROOT):
    profile = Path(profile_home).expanduser().absolute()
    for path in (profile, *profile.parents):
        if path.is_symlink():
            raise ValueError('Use a real profile directory, not a symlink.')
    config_path = profile / 'config.yaml'
    if not config_path.is_file() or config_path.is_symlink():
        raise ValueError('Create a dedicated Hermes profile first; config.yaml must exist.')
    config_text = config_path.read_text(encoding='utf-8')
    config = yaml.safe_load(config_text)
    if not isinstance(config, dict):
        raise ValueError('Hermes config must be a YAML mapping.')
    interpreter = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not interpreter.is_file():
        raise ValueError('Install the repository virtual environment first.')
    entry = {'command': str(interpreter), 'args': [str(root / 'mcp/server.py')],
             'env': {'MCP_ENABLED_APPS': 'typesafe', 'HERMES_HOME': str(profile),
                     'TYPESAFE_RECEIPTS_DB': str(profile / 'typesafe-decisions.sqlite3')},
             'tools': {'include': ['list_typesafe_models', 'analyze_typesafe_decision'],
                       'resources': False, 'prompts': False}}
    servers = config.setdefault('mcp_servers', {})
    if not isinstance(servers, dict):
        raise ValueError('mcp_servers must be a mapping.')
    if 'harqis_typesafe' in servers and servers['harqis_typesafe'] != entry:
        raise ValueError('Existing harqis_typesafe entry differs; review it manually.')
    destination = profile / 'skills/jev-action-triage/SKILL.md'
    for path in (destination, destination.parent, destination.parent.parent):
        if path.is_symlink():
            raise ValueError('Refusing a symlinked skill destination.')
    skill = SKILL.read_text(encoding='utf-8')
    if destination.exists() and destination.read_text(encoding='utf-8') != skill:
        raise ValueError('Installed triage skill differs; review before replacing it.')
    changed = servers.get('harqis_typesafe') != entry or not destination.exists()
    servers['harqis_typesafe'] = entry
    if apply and changed:
        # Preserve the original configuration once; it may contain private values.
        backup = profile / 'config.yaml.before-jev'
        if backup.is_symlink():
            raise ValueError('Refusing a symlinked backup.')
        if not backup.exists():
            with backup.open('x', encoding='utf-8') as stream:
                if os.name != 'nt': os.chmod(backup, 0o600)
                stream.write(config_text)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(skill, encoding='utf-8')
        fd, temporary = tempfile.mkstemp(prefix='.jev-config-', dir=profile)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                yaml.safe_dump(config, stream, sort_keys=False)
            os.replace(temporary, config_path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    return {'mode': 'apply' if apply else 'dry-run', 'changed': changed,
            'profile': str(profile), 'tools': entry['tools']['include'],
            'next': 'Configure TYPESAFE_API_KEY in the host apps.env, reload Hermes MCP, and test the Fleet gateway.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-home', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.profile_home, apply=args.apply)))
    except (ValueError, OSError, yaml.YAMLError):
        parser.exit(1, 'Setup failed: verify the profile, YAML, virtual environment and conflicting files. No credentials are printed.\n')


if __name__ == '__main__':
    main()
