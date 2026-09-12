"""Run queued HFL prompts with local Hermes.

Usage: python scripts/agents/hfl/agent_bridge_runner.py --once
       python scripts/agents/hfl/agent_bridge_runner.py --watch
       python scripts/agents/hfl/agent_bridge_runner.py --daily
       python scripts/agents/hfl/agent_bridge_runner.py --check

Daily scheduling belongs to Hermes; --watch only consumes explicit requests.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]

# Fixed program; private prompts travel on stdin, never in process arguments.
HERMES_PROGRAM = """
import os, sys
from hermes_cli.config import load_config_readonly
model_config = load_config_readonly().get('model', {})
if not isinstance(model_config, dict):
    model_config = {'default': model_config}
os.environ['HERMES_SAFE_MODE'] = '1'
os.environ['HERMES_IGNORE_USER_CONFIG'] = '1'
os.environ['HERMES_IGNORE_RULES'] = '1'
os.environ['HERMES_SESSION_SOURCE'] = 'hfl-agent-bridge'
from cli import main
main(query=sys.stdin.read(), toolsets='web', quiet=True, max_turns=12,
     ignore_user_config=True, ignore_rules=True,
     model=os.environ.get('HFL_AGENT_MODEL') or model_config.get('default') or None,
     provider=os.environ.get('HFL_AGENT_PROVIDER') or model_config.get('provider') or None)
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
        base = os.environ.get('HFL_AGENT_BRIDGE_URL', 'http://127.0.0.1:8000').rstrip('/')
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


def run_hermes(run, heartbeat, *, timeout=1200):
    command, root = hermes_command()
    snapshot = run['snapshot']
    prompt = snapshot['runtime_prompt'] + '\n\n' + json.dumps({key: snapshot.get(key) for key in ('source_key', 'source', 'category_guidance', 'context')}, ensure_ascii=False)
    environment = {key: value for key, value in os.environ.items() if key in {
        'PATH', 'PATHEXT', 'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE',
        'APPDATA', 'LOCALAPPDATA', 'COMSPEC', 'LANG', 'HERMES_HOME', 'HERMES_PROFILE',
        'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY', 'FIRECRAWL_API_KEY',
        'TAVILY_API_KEY', 'HFL_AGENT_MODEL', 'HFL_AGENT_PROVIDER',
    }}
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['PYTHONUTF8'] = '1'
    started = time.monotonic()
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as output:
        process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.PIPE, stdout=output, stderr=output,
                                   text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
                diagnostics.write_text(output.read(250000), encoding='utf-8')
                raise RuntimeError('Hermes execution failed; inspect local Hermes diagnostics.')
            output.seek(0)
            text = output.read(250001)
            if len(text) > 250000:
                raise ValueError('Hermes output exceeded the execution limit.')
            return parse_result(text)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def spool_root():
    return Path(os.environ.get('HARQIS_DATA_ROOT') or REPO_ROOT / '.harqis-data') / 'runtime' / 'agent-bridge-results'


def replay_results(client):
    root = spool_root()
    if not root.exists():
        return
    for path in sorted(root.glob('*.json'))[:50]:
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
            client.event(run, 'plan', 'plan', {'summary': 'Read the frozen instructions, analyze the expected outcome, research or draft within the web-only policy, then review the result against its evidence.'})
            result = run_hermes(run, lambda: client.event(run, 'heartbeat', 'heartbeat', {}))
        except Exception as exc:
            result = {'state': 'failed', 'summary': f'Execution did not finish ({type(exc).__name__}). Inspect the local worker before retrying.', 'complete': False, 'evidence': []}
        result['model'] = os.environ.get('HFL_AGENT_MODEL', 'Hermes provider default')
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
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args()
    bootstrap()
    hermes_command()
    client = BridgeClient()
    try:
        if args.check:
            client.call('queue')
            print('Hermes installation and authenticated bridge are available.')
            return
        if args.daily:
            client.call('sweep', {})
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


if __name__ == '__main__':
    main()
