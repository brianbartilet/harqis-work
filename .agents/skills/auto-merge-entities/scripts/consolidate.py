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
    parser.add_argument('command', choices=['begin', 'status', 'decide', 'batch', 'group', 'finish',
                                            'claim', 'renew', 'release', 'checkpoint', 'evidence'])
    parser.add_argument('run_id', nargs='?')
    parser.add_argument('pair_id', nargs='?')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--compact', action='store_true', help='Lossless deduplicated evidence for begin/status')
    parser.add_argument('--limit', type=int, choices=range(1, 21), help='Status page size (1–20 pairs)')
    parser.add_argument('--worker', help='Stable reviewer ID for idempotent claim recovery')
    parser.add_argument('--claim-token', help='Lease token for batch/group or renew/release')
    parser.add_argument('--max-pairs', type=int, default=8)
    parser.add_argument('--max-bytes', type=int, default=100000)
    parser.add_argument('--lease-seconds', type=int, default=900)
    args = parser.parse_args()
    if args.compact and args.command not in {'begin', 'status'}:
        parser.error('--compact is only valid with begin/status')
    if args.limit and args.command != 'status':
        parser.error('--limit is only valid with status')
    if args.claim_token and args.command not in {'batch', 'group', 'evidence', 'renew', 'release'}:
        parser.error('--claim-token is only valid with batch/group/evidence/renew/release')
    if args.worker and args.command != 'claim':
        parser.error('--worker is only valid with claim')
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
    if args.command in {'batch', 'group', 'evidence'}:
        if not args.file:
            parser.error('--file required')
        path += {'group': '/groups', 'batch': '/decisions', 'evidence': '/evidence'}[args.command]
        body = json.loads(args.file.read_text(encoding='utf-8'))
        if args.claim_token:
            body['claim_token'] = args.claim_token
    elif args.command == 'decide':
        if not args.pair_id or not args.file:
            parser.error('pair_id and --file required')
        path += '/decisions/' + args.pair_id
        body = json.loads(args.file.read_text(encoding='utf-8'))
    elif args.command in {'finish', 'checkpoint'}:
        path += '/' + args.command
    elif args.command == 'claim':
        if not args.worker:
            parser.error('--worker required')
        path += '/claims'
        body = dict(worker_id=args.worker, max_pairs=args.max_pairs,
                    max_bytes=args.max_bytes, lease_seconds=args.lease_seconds)
    elif args.command in {'renew', 'release'}:
        if not args.claim_token:
            parser.error('--claim-token required')
        path += '/claims/' + args.claim_token
        body = dict(action=args.command, lease_seconds=args.lease_seconds)
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
            if any('error' in item for item in result.get('results', [])) or result.get('required_bytes'):
                return 1
    except httpx.TransportError as exc:
        print(json.dumps({'error': type(exc).__name__, 'run_id': args.run_id, 'pair_id': args.pair_id}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
