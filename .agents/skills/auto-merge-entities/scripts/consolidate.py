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
    parser.add_argument('command', choices=['begin', 'status', 'decide', 'batch', 'group', 'finish'])
    parser.add_argument('run_id', nargs='?')
    parser.add_argument('pair_id', nargs='?')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--compact', action='store_true', help='Lossless deduplicated evidence for begin/status')
    parser.add_argument('--limit', type=int, choices=range(1, 21), help='Status page size (1–20 pairs)')
    args = parser.parse_args()
    if args.compact and args.command not in {'begin', 'status'}:
        parser.error('--compact is only valid with begin/status')
    if args.limit and args.command != 'status':
        parser.error('--limit is only valid with status')
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
    if args.command in {'batch', 'group'}:
        if not args.file:
            parser.error('--file required')
        path += '/groups' if args.command == 'group' else '/decisions'
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
            params = {}
            if args.compact:
                params['compact'] = 'true'
            if args.limit:
                params['limit'] = args.limit
            response = client.get(url, params=params) if args.command == 'status' else client.post(url, params=params, json=body)
            try:
                result = response.json()
            except ValueError:
                print(json.dumps({'status': response.status_code, 'detail': 'Non-JSON API response; retain payload for recovery'}))
                return 1
            if response.is_error:
                print(json.dumps({'status': response.status_code, 'detail': result.get('detail', 'API error')}))
                return 1
            if args.compact and result.get('format') != 'anchor-packets-v1':
                print(json.dumps({'error': 'Compact packets unsupported by this server; use the compatible legacy path or deploy separately'}))
                return 1
            print(json.dumps(result, ensure_ascii=True, separators=(',', ':')))
    except httpx.TransportError as exc:
        print(json.dumps({'error': type(exc).__name__, 'run_id': args.run_id, 'pair_id': args.pair_id}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
