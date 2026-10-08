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
import threading
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
REPLAY_LOCK = threading.Lock()


class InputAttachmentError(ValueError):
    """A controlled validation message safe to show to the task owner."""

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


def hermes_command(program=HERMES_PROGRAM):
    executable = shutil.which('hermes')
    root = os.environ.get('HFL_AGENT_HERMES_ROOT', '')
    if not root and executable:
        root = next((str(parent) for parent in Path(executable).resolve().parents
                     if (parent / 'cli.py').is_file()), '')
    if not root and (Path.home() / '.hermes/hermes-agent/cli.py').is_file():
        root = str(Path.home() / '.hermes/hermes-agent')
    if not root:
        raise RuntimeError('Install Hermes or configure HFL_AGENT_HERMES_ROOT.')
    home = Path(root).expanduser().resolve()
    interpreter = home / ('venv/Scripts/python.exe' if os.name == 'nt' else 'venv/bin/python')
    launcher = home / '.hermes/bin/hermes'
    if launcher.is_file() and os.name != 'nt':
        resolved = subprocess.run([str(launcher), '--print-runtime-command'],
                                  capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
        runtime = json.loads(resolved.stdout)
        if not isinstance(runtime, list) or not runtime or not isinstance(runtime[0], str):
            raise RuntimeError('Hermes returned an invalid runtime command.')
        interpreter = Path(runtime[0])
        program = ('import sys; sys.path.insert(0, ' + repr(str(home)) + '); '
                   'import hermes_bootstrap\n' + program)
    if not interpreter.is_file() or not (home / 'cli.py').is_file():
        raise RuntimeError('HFL_AGENT_HERMES_ROOT must point to the Hermes source installation with its venv.')
    return [str(interpreter), '-c', program], home


def parse_result(output, *, board_planning=False):
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
    if board_planning:
        # Older board prompts did not specify these field types. Preserve their
        # valid proposals while converting the observed structured variants.
        plan = result.get('plan')
        if isinstance(plan, list) and 0 < len(plan) <= 30 and all(isinstance(step, str) and step.strip() for step in plan):
            result['plan'] = '\n'.join('- ' + step for step in plan)
        evidence = result.get('evidence')
        if isinstance(evidence, list):
            result['evidence'] = [
                next((ref[key] for key in ('id', 'ref', 'reference')
                      if isinstance(ref.get(key), str) and ref[key].strip()), ref)
                if isinstance(ref, dict) else ref for ref in evidence]
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
    if any(key in result for key in ('matrix', 'matrix_confidence', 'matrix_reason')):
        from workflows.hfl.timeline_store import validate_matrix
        validate_matrix(result)
    if 'board_ids' in result:
        from workflows.hfl.intent_boards import board_ids
        board_ids(result['board_ids'])
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
        import httpx
        # Only replay idempotent terminal polling and keyed output delivery.
        retryable = path.startswith('terminals/') and (
            path.endswith('/poll') or (path.endswith('/output') and payload and payload.get('key')))
        attempts = 4 if retryable else 1
        for attempt in range(attempts):
            try:
                options = {'timeout': 5} if retryable else {}
                response = self.client.get(path, **options) if payload is None else self.client.post(path, json=payload, **options)
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {502, 503, 504}:
                    raise
                if attempt + 1 == attempts:
                    raise
                time.sleep(2 ** attempt)

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
    from workflows.hfl.attachment_limits import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES
    root = spool_root() / 'workspaces' / run['id'] / 'inputs'
    if root.is_symlink() or not root.resolve().is_relative_to((spool_root() / 'workspaces').resolve()):
        raise ValueError('Input directory cannot be a symlink.')
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    attachments = run['snapshot']['source'].get('attachments', [])
    if len(attachments) > MAX_FILES:
        raise InputAttachmentError(f'This task has {len(attachments)} input attachments; the limit is {MAX_FILES}.')
    for item in attachments:
        name = item['filename']
        if not re.fullmatch(r'[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?', name) or not re.fullmatch('[a-f0-9]{32}', item['id']):
            raise ValueError('Invalid input filename.')
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Input escapes the workspace.')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as target:
                temporary = Path(target.name)
                size = 0
                digest = hashlib.sha256()
                with client.client.stream('GET', 'runs/' + run['id'] + '/inputs/' + item['id'],
                                         headers={'X-Execution-Lease': run['lease_token']}) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                            raise InputAttachmentError('Input attachments allow 500 MB per file and 25,000 MB total.')
                        digest.update(chunk)
                        target.write(chunk)
                if size != item['size'] or digest.hexdigest() != item['digest']:
                    raise InputAttachmentError('Input attachment integrity check failed. Reattach the original file before retrying.')
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


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
    settings = dict(snapshot.get('execution_settings', {'agent_mode': 'restricted'}))
    if snapshot.get('kind') == 'actionable':
        settings['agent_repository'] = settings.get('agent_repository') or str(REPO_ROOT)
    timeout = settings.get('agent_timeout_seconds', timeout)
    from scripts.agents.hfl.action_terminal import Workspace
    checkout = Workspace(spool_root() / 'repositories' / run['id'], run['id'], settings)
    workspace = spool_root() / 'workspaces' / run['id']
    workspace.mkdir(parents=True, exist_ok=True)
    prompt = execution_prompt(run, workspace)
    if checkout.repo:
        prompt += ('\n\nRepository policy: edit only the isolated checkout at ' + str(checkout.path)
                   + '. Do not edit the primary checkout. For another repository, ask the owner to configure it before editing. Do not merge or push without explicit instructions.')
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
    environment['TERMINAL_CWD'] = str(checkout.path if checkout.repo else workspace.resolve())
    environment['TERMINAL_ENV'] = 'local'
    started = time.monotonic()
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as output:
        process = subprocess.Popen(command, cwd=checkout.path if checkout.repo else workspace, env=environment, stdin=subprocess.PIPE, stdout=output, stderr=output,
                                   text=True, encoding='utf-8', start_new_session=os.name != 'nt', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except BrokenPipeError:
                # The child can fail during imports before accepting the prompt.
                # Still wait and capture stderr through the normal failure path.
                pass
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
            try:
                result = parse_result(text, board_planning=run['snapshot'].get('kind') == 'mindmap')
            except ValueError:
                diagnostics = spool_root() / ('hermes-' + run.get('id', 'check') + '.log')
                diagnostics.write_text(text, encoding='utf-8')
                raise
            metadata = next((line.removeprefix('HFL_BRIDGE_RUNTIME=') for line in reversed(text.splitlines()) if line.startswith('HFL_BRIDGE_RUNTIME=')), '{}')
            runtime = json.loads(metadata)
            result['model'] = str(runtime.get('model') or 'provider default')[:200]
            result['provider'] = str(runtime.get('provider') or 'auto')[:200]
            result['runtime'] = runtime
            sessions = re.findall(r'^session_id:\s*([A-Za-z0-9_-]+)', text, flags=re.MULTILINE)
            result['session_id'] = sessions[-1] if sessions else ''
            if checkout.repo:
                result.setdefault('artifacts', []).append('repository-changes.zip')
            return result
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            if checkout.repo:
                checkout.preserve(workspace)


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
    with REPLAY_LOCK:
        replay_results(client)
    runs = client.call('queue')['runs']
    for queued in runs[:limit]:
        try:
            run = client.call('runs/' + queued['id'] + '/claim', {'host': socket.gethostname()})
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
            if run['snapshot'].get('kind') == 'actionable' or run['snapshot'].get('execution_settings', {}).get('agent_repository'):
                from scripts.agents.hfl.action_terminal import Workspace
                workspace_settings = dict(run['snapshot'].get('execution_settings', {}))
                workspace_settings['agent_repository'] = workspace_settings.get('agent_repository') or str(REPO_ROOT)
                checkout = Workspace(spool_root() / 'repositories' / run['id'], run['id'], workspace_settings)
                checkout.cleanup()
        except Exception as exc:
            result = {'state': 'failed', 'blocked_reason': 'integration', 'summary': f'Execution did not finish ({type(exc).__name__}). Inspect the local worker before retrying.', 'complete': False, 'evidence': []}
            if isinstance(exc, InputAttachmentError):
                result['summary'] = str(exc)
            archive = spool_root() / 'workspaces' / run['id'] / 'repository-changes.zip'
            if archive.exists():
                try:
                    result['artifacts'] = [archive.name]
                    upload_artifacts(client, run, result)
                    from scripts.agents.hfl.action_terminal import Workspace
                    workspace_settings = dict(run['snapshot'].get('execution_settings', {}))
                    workspace_settings['agent_repository'] = workspace_settings.get('agent_repository') or str(REPO_ROOT)
                    Workspace(spool_root() / 'repositories' / run['id'], run['id'], workspace_settings).cleanup()
                except Exception:
                    result['summary'] += ' The recovery archive and worktree remain on the worker because attachment or cleanup failed.'
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
    stop = threading.Event()
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
            command, root = hermes_command('from hermes_cli.config import load_config_readonly\nimport cli')
            subprocess.run(command, cwd=root, check=True, timeout=60, capture_output=True)
            client.call('queue')
            print('Hermes installation and authenticated bridge are available.')
            return
        if args.daily or args.dispatch:
            client.call('sweep', {})
        if args.dispatch:
            return
        if args.watch:
            from scripts.agents.hfl.action_terminal import watch_terminals
            threading.Thread(target=watch_terminals, args=(sys.modules[__name__], stop), daemon=True).start()
            def consume_one():
                connection = BridgeClient()
                try:
                    consume(connection, limit=1)
                finally:
                    connection.client.close()
            with ThreadPoolExecutor(max_workers=32) as pool:
                pending = set()
                while True:
                    pending = {job for job in pending if not job.done()}
                    try:
                        capacity = client.call('settings')['agent_concurrency']
                        if len(pending) < capacity:
                            pending.add(pool.submit(consume_one))
                    except Exception as exc:
                        print('Bridge worker unavailable: ' + type(exc).__name__, file=sys.stderr)
                    time.sleep(2)
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
        stop.set()
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
