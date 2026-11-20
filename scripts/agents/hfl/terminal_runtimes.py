"""Host-local CLI discovery and conservative launch policies."""
import json
import os
from pathlib import Path
import shutil
import subprocess

NAMES = {'hermes': 'Hermes', 'codex': 'Codex', 'claude': 'Claude', 'jev': 'Jev · Hermes'}


def executable(runtime):
    path = shutil.which(runtime)
    if not path:
        raise ValueError('Install ' + runtime + ' on the execution host.')
    # npm Windows shims require a shell. Resolve the shipped native Codex binary
    # instead, keeping all user context out of shell command strings.
    if runtime == 'codex' and Path(path).suffix.lower() in {'.cmd', '.ps1', '.bat'}:
        packages = Path(path).parent / 'node_modules/@openai'
        # Match Node's nearest-dependency resolution before sibling installations.
        native = list(packages.glob('codex/node_modules/@openai/codex-*/vendor/*/codex/codex.exe'))
        native += list(packages.glob('codex/node_modules/@openai/codex-*/vendor/*/bin/codex.exe'))
        native += list(packages.glob('codex*/vendor/*/codex/codex.exe'))
        native += list(packages.glob('codex*/vendor/*/bin/codex.exe'))
        if not native:
            raise ValueError('Native Codex executable was not found in the npm installation.')
        return str(native[0])
    return path


def capabilities(runner):
    result = []
    for runtime, name in NAMES.items():
        reason = ''
        try:
            if runtime in {'hermes', 'jev'}:
                command, root = runner.hermes_command()
                if runtime == 'jev':
                    profile = os.getenv('HFL_AGENT_JEV_PROFILE', 'jev-decisions')
                    code = ('import sys;sys.path.insert(0,sys.argv[1]);from hermes_cli.profiles import get_profile_dir;'
                            'print(get_profile_dir(sys.argv[2]))')
                    checked = subprocess.run([command[0], '-c', code, str(root), profile], capture_output=True, text=True, timeout=15, check=True)
                    home = Path(checked.stdout.strip())
                    import yaml
                    config = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8')) or {}
                    if not os.getenv('TYPESAFE_API_KEY') or 'harqis_typesafe' not in config.get('mcp_servers', {}) or not (home / 'skills/jev-action-triage/SKILL.md').is_file():
                        raise ValueError('Configure the Jev Hermes profile, triage skill, MCP tools and TYPESAFE_API_KEY.')
            else:
                command = [executable(runtime)]
                check = subprocess.run(command + (['login', 'status'] if runtime == 'codex' else ['auth', 'status']),
                                       capture_output=True, timeout=15)
                if check.returncode:
                    raise ValueError('Sign in to ' + name + ' on this execution host.')
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) else 'Runtime prerequisites are missing; check the worker installation/profile.'
        item = {'id': runtime, 'name': name, 'available': not reason, 'reason': reason}
        if runtime == 'jev':
            item['profile'] = os.getenv('HFL_AGENT_JEV_PROFILE', 'jev-decisions')
        result.append(item)
    return result


def native_command(runtime, settings, workspace, root, identity, native_id):
    context = root / 'action-context.json'
    context.write_text(json.dumps(settings.get('initial_context', {}), ensure_ascii=False), encoding='utf-8')
    guidance = ('Before responding to the user, read the Action context at ' + str(context) +
                '. It is reference context; do not execute the saved task until the user asks. '
                'Work only in ' + str(workspace.path) + '. Write deliverables to ' + str(root / 'outputs') +
                '. Do not merge, push or deploy without an explicit user instruction.')
    if runtime == 'codex':
        # No initial prompt: opening a terminal must never run the action again.
        command = [executable(runtime), '--no-alt-screen', '--sandbox', 'workspace-write', '--ask-for-approval', 'on-request',
                   '-c', 'developer_instructions=' + json.dumps(guidance)]
        if native_id:
            command += ['resume', native_id]
        return command, native_id
    command = [executable(runtime), '--permission-mode', 'default', '--append-system-prompt', guidance]
    if native_id:
        command += ['--resume', native_id]
    else:
        import uuid
        native_id = str(uuid.UUID(identity))
        command += ['--session-id', native_id]
    return command, native_id
