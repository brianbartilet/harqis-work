"""Authenticated API helper; never prints tokens or writes the entity store."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def main():
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    os.chdir(ROOT)
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    import httpx
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['begin', 'status', 'decide', 'batch', 'finish'])
    parser.add_argument('run_id', nargs='?')
    parser.add_argument('pair_id', nargs='?')
    parser.add_argument('--file', type=Path)
    args = parser.parse_args()
    # The canonical host intentionally leaves the remote corpus URL unset.
    # Its explicitly configured owning frontend exposes the same entity API.
    base = (os.environ.get('HFL_CORPUS_API_URL') or os.environ.get('HFL_AGENT_BRIDGE_URL') or '').rstrip('/')
    token = os.environ.get('HFL_CORPUS_API_TOKEN', '')
    if not base or not token or '${' in base or '${' in token:
        parser.error('Configure HFL_CORPUS_API_URL (or the owning HFL_AGENT_BRIDGE_URL) and HFL_CORPUS_API_TOKEN')
    path = '/consolidation/begin' if args.command == 'begin' else '/consolidation/' + (args.run_id or '')
    body = {}
    if args.command != 'begin' and not args.run_id:
        parser.error('run_id required')
    if args.command == 'batch':
        if not args.file:
            parser.error('--file required')
        path += '/decisions'
        body = json.loads(args.file.read_text(encoding='utf-8'))
    elif args.command == 'decide':
        if not args.pair_id or not args.file:
            parser.error('pair_id and --file required')
        path += '/decisions/' + args.pair_id
        body = json.loads(args.file.read_text(encoding='utf-8'))
    elif args.command == 'finish':
        path += '/finish'
    try:
        with httpx.Client(timeout=180, headers={'Authorization': 'Bearer ' + token}) as client:
            url = base + '/api/hfl/entities' + path
            response = client.get(url) if args.command == 'status' else client.post(url, json=body)
            if response.is_error:
                print(json.dumps({'status': response.status_code, 'detail': response.json().get('detail', 'API error')}))
                return 1
            print(json.dumps(response.json(), ensure_ascii=True))
    except httpx.TransportError as exc:
        print(json.dumps({'error': type(exc).__name__, 'run_id': args.run_id, 'pair_id': args.pair_id}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
