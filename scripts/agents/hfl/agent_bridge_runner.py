"""Run queued HFL prompts with local Hermes.

Usage: python scripts/agents/hfl/agent_bridge_runner.py --once
       python scripts/agents/hfl/agent_bridge_runner.py --watch
       python scripts/agents/hfl/agent_bridge_runner.py --dispatch
       python scripts/agents/hfl/agent_bridge_runner.py --smoke
       python scripts/agents/hfl/agent_bridge_runner.py --check

Minute discovery belongs to Hermes; --watch consumes queued requests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]

# Fixed program; private prompts travel on stdin, never in process arguments.
HERMES_PROGRAM = """
import json, os, sys
sys.path.insert(0, os.environ['HFL_AGENT_HERMES_ROOT'])
settings = json.loads(os.environ.get('HFL_AGENT_EXECUTION_SETTINGS', '{}'))
trusted = settings.get('agent_mode') == 'trusted'
profile = settings.get('hermes_profile')
if profile:
    from hermes_cli.profiles import get_profile_dir
    profile_dir = get_profile_dir(profile)
    if not profile_dir.is_dir():
        raise RuntimeError('Configured Hermes profile does not exist.')
    os.environ['HERMES_HOME'] = str(profile_dir)
    os.environ['HERMES_PROFILE'] = profile
    os.environ.pop('HERMES_CONFIG', None)
    os.environ.pop('HERMES_ENV', None)
for key in ('HERMES_SAFE_MODE', 'HERMES_IGNORE_USER_CONFIG', 'HERMES_IGNORE_RULES'):
    if trusted:
        os.environ.pop(key, None)
    else:
        os.environ[key] = '1'
from hermes_cli.config import load_config_readonly
config = load_config_readonly()
model_config = config.get('model', {})
if not isinstance(model_config, dict):
    model_config = {'default': model_config}
os.environ['HERMES_SESSION_SOURCE'] = 'hfl-agent-bridge'
from cli import main
selected_model = settings.get('agent_model') or os.environ.get('HFL_AGENT_MODEL') or model_config.get('default') or None
selected_provider = settings.get('agent_provider') or os.environ.get('HFL_AGENT_PROVIDER') or model_config.get('provider') or None
toolsets = (settings.get('agent_toolsets') or None) if trusted else 'web,terminal,file,code_execution'
runtime = {'model': selected_model, 'provider': selected_provider,
           'profile': profile or os.environ.get('HERMES_PROFILE') or 'default',
           'mode': 'trusted' if trusted else 'restricted',
           'toolsets': toolsets or 'profile defaults',
           'configured_mcp_servers': list(config.get('mcp_servers') or {}) if trusted else []}
print('HFL_BRIDGE_RUNTIME=' + json.dumps(runtime), flush=True)
if os.environ.get('HFL_AGENT_CAPABILITY_CHECK') == '1':
    main(list_tools=True, toolsets=toolsets, quiet=True,
         ignore_user_config=not trusted, ignore_rules=not trusted)
    sys.exit(0)
main(query=sys.stdin.read(), toolsets=toolsets, quiet=True, max_turns=settings.get('agent_max_turns', 30),
     ignore_user_config=not trusted, ignore_rules=not trusted,
     model=selected_model, provider=selected_provider)
"""


def bootstrap():
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(REPO_ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))


def hermes_command():
    executable = shutil.which('hermes')
    root = os.environ.get('HFL_AGENT_HERMES_ROOT', '')
    if not root and executable:
        root = str(Path(executable).resolve().parents[2])
    if not root and (Path.home() / '.hermes/hermes-agent/cli.py').is_file():
        root = str(Path.home() / '.hermes/hermes-agent')
    if not root:
        raise RuntimeError('Install Hermes or configure HFL_AGENT_HERMES_ROOT.')
    home = Path(root).expanduser().resolve()
    interpreter = home / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')
    if not interpreter.is_file() or not (home / 'cli.py').is_file():
        raise RuntimeError('HFL_AGENT_HERMES_ROOT must point to the Hermes source installation with its venv.')
    return [str(interpreter), '-c', HERMES_PROGRAM], home


def parse_result(output):
    decoder = json.JSONDecoder()
    candidates = []
    for position, character in enumerate(output):
        if character != '{':
            continue
        try:
            result, _ = decoder.raw_decode(output[position:])
        except ValueError:
            continue
        if isinstance(result, dict) and all(key in result for key in ('plan', 'summary', 'evidence', 'complete', 'state')):
            candidates.append(result)
    if len(candidates) != 1:
        raise ValueError('Hermes did not return one structured execution result.')
    result = candidates[0]
    if result['state'] not in {'succeeded', 'failed', 'awaiting_input'} or type(result['complete']) is not bool:
        raise ValueError('Invalid Hermes outcome.')
    if result.get('blocked_reason') not in (None, 'input', 'integration'):
        raise ValueError('Invalid blocker type.')
    if not isinstance(result.get('question', ''), str) or len(result.get('question', '')) > 8000:
        raise ValueError('Invalid input question.')
    for field in ('plan', 'summary'):
        if not isinstance(result[field], str) or not result[field].strip() or len(result[field]) > 100000:
            raise ValueError('Invalid Hermes plan or output.')
    evidence = result['evidence']
    if not isinstance(evidence, list) or len(evidence) > 30 or any(not isinstance(ref, str) or len(ref) > 2000 for ref in evidence):
        raise ValueError('Invalid Hermes evidence.')
    if result['state'] == 'succeeded' and not evidence:
        raise ValueError('Successful results require evidence.')
    return result


class BridgeClient:
    def __init__(self):
        import httpx
        base = os.environ.get('HFL_AGENT_BRIDGE_URL', 'http://127.0.0.1:' + os.environ.get('PORT', '8080')).rstrip('/')
        parsed = urlparse(base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
            raise ValueError('Bridge URL must be a server origin without credentials.')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}):
            raise ValueError('Use HTTPS for a remote bridge or HTTP on loopback.')
        token = os.environ.get('HFL_AGENT_BRIDGE_TOKEN', '').strip()
        if not token:
            raise ValueError('Configure HFL_AGENT_BRIDGE_TOKEN on the owning frontend and worker.')
        self.client = httpx.Client(base_url=base + '/api/hfl-agent/', headers={'Authorization': 'Bearer ' + token}, timeout=45, follow_redirects=False, trust_env=False)

    def call(self, path, payload=None):
        response = self.client.get(path) if payload is None else self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def event(self, run, key, kind, payload):
        return self.call('runs/' + run['id'] + '/events', {'lease_token': run['lease_token'], 'event_key': key, 'kind': kind, 'payload': payload})


def execution_prompt(run, workspace):
    snapshot = run['snapshot']
    return snapshot['runtime_prompt'] + '\n\n' + json.dumps({
        **{key: snapshot.get(key) for key in ('source_key', 'source', 'category_guidance', 'context', 'occurrence_date', 'continuation')},
        'artifact_directory': str(workspace.resolve()),
        'input_directory': str((workspace / 'inputs').resolve()),
        'execution_settings': snapshot.get('execution_settings', {'agent_mode': 'restricted'}),
        'operation_scope': snapshot.get('operation_scope', run.get('request_key', run['id'])),
    }, ensure_ascii=False)


def restore_input_attachments(client, run):
    """Materialize the immutable input manifest on this worker, checking every byte."""
    root = spool_root() / 'workspaces' / run['id'] / 'inputs'
    if root.is_symlink() or not root.resolve().is_relative_to((spool_root() / 'workspaces').resolve()):
        raise ValueError('Input directory cannot be a symlink.')
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    attachments = run['snapshot']['source'].get('attachments', [])
    if len(attachments) > 10:
        raise ValueError('Too many input attachments.')
    for item in attachments:
        name = item['filename']
        if not re.fullmatch(r'[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?', name) or not re.fullmatch('[a-f0-9]{32}', item['id']):
            raise ValueError('Invalid input filename.')
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Input escapes the workspace.')
        content = bytearray()
        with client.client.stream('GET', 'runs/' + run['id'] + '/inputs/' + item['id'],
                                 headers={'X-Execution-Lease': run['lease_token']}) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                total += len(chunk)
                if len(content) > 50 * 1024 * 1024 or total > 200 * 1024 * 1024:
                    raise ValueError('Input attachment size limit exceeded.')
        if len(content) != item['size'] or hashlib.sha256(content).hexdigest() != item['digest']:
            raise ValueError('Input attachment integrity check failed.')
        path.write_bytes(content)


def restore_prior_artifacts(client, run):
    """Fetch only declared prior files with the new attempt's execution lease."""
    workspace = spool_root() / 'workspaces' / run['id']
    workspace.mkdir(parents=True, exist_ok=True)
    for artifact in run['snapshot'].get('continuation', {}).get('artifacts', []):
        name = artifact['name']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', name):
            raise ValueError('Invalid prior artifact filename.')
        path = workspace / name
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError('Prior artifact escapes the workspace.')
        with client.client.stream('GET', 'runs/' + run['id'] + '/prior-artifacts/' + name,
                                 headers={'X-Execution-Lease': run['lease_token']}) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 20 * 1024 * 1024:
                    raise ValueError('Prior artifact exceeds 20 MB.')
        if len(content) != artifact['size'] or hashlib.sha256(content).hexdigest() != artifact['digest']:
            raise ValueError('Prior artifact integrity check failed.')
        path.write_bytes(content)


def run_hermes(run, heartbeat, *, timeout=1200):
    command, root = hermes_command()
    snapshot = run['snapshot']
    settings = snapshot.get('execution_settings', {'agent_mode': 'restricted'})
    timeout = settings.get('agent_timeout_seconds', timeout)
    workspace = spool_root() / 'workspaces' / run['id']
    workspace.mkdir(parents=True, exist_ok=True)
    prompt = execution_prompt(run, workspace)
    environment = {key: value for key, value in os.environ.items() if key in {
        'PATH', 'PATHEXT', 'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE',
        'APPDATA', 'LOCALAPPDATA', 'COMSPEC', 'LANG', 'HERMES_HOME', 'HERMES_PROFILE',
        'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY', 'FIRECRAWL_API_KEY',
        'TAVILY_API_KEY', 'HFL_AGENT_MODEL', 'HFL_AGENT_PROVIDER',
    }}
    if settings.get('agent_mode') == 'trusted':
        environment = dict(os.environ)
    # The queue lease and owner API token are not needed by the agent subprocess.
    environment.pop('HFL_AGENT_BRIDGE_TOKEN', None)
    environment.pop('HFL_AGENT_CAPABILITY_CHECK', None)
    environment['HFL_AGENT_EXECUTION_SETTINGS'] = json.dumps(settings)
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['PYTHONUTF8'] = '1'
    environment['HFL_AGENT_HERMES_ROOT'] = str(root)
    environment['TERMINAL_CWD'] = str(workspace.resolve())
    environment['TERMINAL_ENV'] = 'local'
    started = time.monotonic()
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as output:
        process = subprocess.Popen(command, cwd=workspace, env=environment, stdin=subprocess.PIPE, stdout=output, stderr=output,
                                   text=True, encoding='utf-8', start_new_session=os.name != 'nt', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            process.stdin.write(prompt)
            process.stdin.close()
            while True:
                try:
                    process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started > timeout:
                        raise TimeoutError('Hermes execution timed out.')
                    heartbeat()
            if process.returncode:
                output.seek(0)
                diagnostics = spool_root() / ('hermes-' + run.get('id', 'check') + '.log')
                diagnostics.parent.mkdir(parents=True, exist_ok=True)
                diagnostics.write_text(redact_credentials(output.read(250000), environment), encoding='utf-8')
                raise RuntimeError('Hermes execution failed; inspect local Hermes diagnostics.')
            output.seek(0)
            text = output.read(250001)
            if len(text) > 250000:
                raise ValueError('Hermes output exceeded the execution limit.')
            text = redact_credentials(text, environment)
            result = parse_result(text)
            metadata = next((line.removeprefix('HFL_BRIDGE_RUNTIME=') for line in reversed(text.splitlines()) if line.startswith('HFL_BRIDGE_RUNTIME=')), '{}')
            runtime = json.loads(metadata)
            result['model'] = str(runtime.get('model') or 'provider default')[:200]
            result['provider'] = str(runtime.get('provider') or 'auto')[:200]
            result['runtime'] = runtime
            sessions = re.findall(r'^session_id:\s*([A-Za-z0-9_-]+)', text, flags=re.MULTILINE)
            result['session_id'] = sessions[-1] if sessions else ''
            return result
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)


def spool_root():
    return Path(os.environ.get('HARQIS_DATA_ROOT') or REPO_ROOT / '.harqis-data') / 'runtime' / 'agent-bridge-results'


def redact_credentials(text, environment):
    """Defense in depth for known environment secrets, not arbitrary file secrets."""
    values = {value for key, value in environment.items()
              if re.search(r'(KEY|TOKEN|PASSWORD|SECRET)', key, re.I) and len(value) >= 8}
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    return text


def replay_results(client):
    root = spool_root()
    if not root.exists():
        return
    for path in sorted(root.glob('*.json')):
        receipt = json.loads(path.read_text(encoding='utf-8'))
        if receipt.get('delivered'):
            continue
        try:
            client.event(receipt['run'], 'result', receipt['result']['state'], receipt['result'])
        except Exception:
            continue
        receipt['delivered'] = True
        save_receipt(path, receipt)


def save_receipt(path, receipt):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def upload_artifacts(client, run, result):
    """Publish only explicitly declared files contained in this attempt's workspace."""
    artifacts = result.get('artifacts', [])
    if not isinstance(artifacts, list) or len(artifacts) > 30:
        raise ValueError('Expected at most 30 artifact filenames.')
    root = (spool_root() / 'workspaces' / run['id']).resolve()
    links = []
    for name in artifacts:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', name):
            raise ValueError('Artifacts must use simple relative filenames.')
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Artifact is outside the workspace, missing, or exceeds 20 MB.')
        response = client.client.post('runs/' + run['id'] + '/artifacts/' + name,
            headers={'X-Execution-Lease': run['lease_token'], 'Content-Type': 'application/octet-stream'}, content=path.read_bytes())
        response.raise_for_status()
        url = response.json()['url']
        result['summary'] = result['summary'].replace('](' + name + ')', '](' + url + '?view=true)')
        links.append(f'[{name}]({url}?view=true) · [Download]({url})')
    if links:
        result['summary'] += '\n\n### Files\n\n' + '\n\n'.join(links)


def consume(client, *, limit=10):
    import httpx
    replay_results(client)
    runs = client.call('queue')['runs']
    for queued in runs[:limit]:
        try:
            run = client.call('runs/' + queued['id'] + '/claim', {})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {404, 409}:
                continue
            raise
        try:
            client.event(run, 'plan', 'plan', {'summary': 'Read the prompt and supporting context, perform the requested task with available tools, and verify the output against the prompt.', 'execution_settings': run['snapshot'].get('execution_settings', {})})
            restore_input_attachments(client, run)
            restore_prior_artifacts(client, run)
            result = run_hermes(run, lambda: client.event(run, 'heartbeat', 'heartbeat', {}))
            upload_artifacts(client, run, result)
        except Exception as exc:
            result = {'state': 'failed', 'blocked_reason': 'integration', 'summary': f'Execution did not finish ({type(exc).__name__}). Inspect the local worker before retrying.', 'complete': False, 'evidence': []}
        result.setdefault('model', os.environ.get('HFL_AGENT_MODEL', 'Hermes provider default'))
        receipt = {'run': {'id': run['id'], 'lease_token': run['lease_token']}, 'result': result, 'delivered': False}
        path = spool_root() / (run['id'] + '.json')
        save_receipt(path, receipt)
        client.event(run, 'result', result['state'], result)
        receipt['delivered'] = True
        save_receipt(path, receipt)
        print(f"Agent run {run['id']}: {result['state']}")
    client.call('deliver', {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--watch', action='store_true')
    mode.add_argument('--daily', action='store_true')
    mode.add_argument('--dispatch', action='store_true', help='Discover due work without executing it (Hermes cron).')
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--capabilities', action='store_true', help='Discover profile tools without inference or consuming tasks.')
    mode.add_argument('--smoke', action='store_true', help='Run two synthetic file tasks, without consuming the production queue.')
    args = parser.parse_args()
    bootstrap()
    hermes_command()
    if args.smoke:
        smoke()
        return
    client = BridgeClient()
    try:
        if args.capabilities:
            settings = client.call('settings')
            command, root = hermes_command()
            environment = dict(os.environ)
            environment.pop('HFL_AGENT_BRIDGE_TOKEN', None)
            environment.update(HFL_AGENT_EXECUTION_SETTINGS=json.dumps(settings),
                               HFL_AGENT_HERMES_ROOT=str(root), HFL_AGENT_CAPABILITY_CHECK='1')
            subprocess.run(command, env=environment, cwd=root, check=True, timeout=120)
            return
        if args.check:
            client.call('queue')
            print('Hermes installation and authenticated bridge are available.')
            return
        if args.daily or args.dispatch:
            client.call('sweep', {})
        if args.dispatch:
            return
        while True:
            try:
                consume(client)
            except Exception as exc:
                if not args.watch:
                    raise
                print('Bridge worker unavailable: ' + type(exc).__name__, file=sys.stderr)
            if not args.watch:
                break
            time.sleep(15)
    finally:
        client.client.close()


def smoke():
    sessions = []
    for _ in range(2):
        run = {'id': 'smoke-' + uuid.uuid4().hex, 'snapshot': {
            'runtime_prompt': (REPO_ROOT / 'workflows/hfl/prompts/agent_bridge.md').read_text(encoding='utf-8'),
            'source_key': 'smoke:synthetic', 'source': {'title': 'Synthetic deployment check',
                'prompt': 'Create hello.md in artifact_directory with exactly this content: "HFL bridge smoke passed" (without quotation marks; a final newline is allowed). Read it to verify the content. Return it in artifacts and cite smoke:synthetic. Do not use the web or modify any other files.'}}}
        result = run_hermes(run, lambda: None)
        path = spool_root() / 'workspaces' / run['id'] / 'hello.md'
        if not result.get('complete') or result.get('state') != 'succeeded' or not result.get('session_id') or not path.is_file() or path.read_text(encoding='utf-8').strip() != 'HFL bridge smoke passed':
            raise RuntimeError('Synthetic Hermes file execution did not pass.')
        sessions.append(result['session_id'])
        print('Synthetic Hermes file task passed; session ' + result['session_id'])
    if sessions[0] == sessions[1]:
        raise RuntimeError('Hermes reused an execution session.')
    print('Fresh-session and file-output checks passed. No production tasks consumed.')


if __name__ == '__main__':
    main()
