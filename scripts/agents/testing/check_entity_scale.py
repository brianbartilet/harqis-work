"""Read-only scale check; all index/ledger writes use a disposable database.

Usage: python scripts/agents/testing/check_entity_scale.py --size 8400 [--live]
Live mode fetches directory pages via GET only. Output contains aggregate counts,
timings and sizes, never entity names, excerpts or credentials.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    os.chdir(ROOT)
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=8400)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--baseline-ref', help='Trusted local Git revision to compare candidate discovery')
    args = parser.parse_args()
    if args.size < 2:
        parser.error('--size must be at least 2')
    if args.live:
        import httpx
        base = (os.environ.get('HFL_CORPUS_API_URL') or os.environ.get('HFL_AGENT_BRIDGE_URL') or '').rstrip('/')
        token = os.environ.get('HFL_CORPUS_API_TOKEN', '')
        if not base or not token:
            parser.error('Corpus API configuration required')
        rows, total = [], None
        with httpx.Client(timeout=120, headers={'Authorization': 'Bearer ' + token}) as client:
            while total is None or len(rows) < total:
                response = client.get(base + '/api/hfl/entities', params={'offset': len(rows), 'limit': 500})
                if response.status_code != 200:
                    raise RuntimeError(f'Directory HTTP status {response.status_code}')
                page = response.json()
                if total is not None and total != page['total']:
                    raise RuntimeError('Directory changed during paging; rerun the read-only check')
                total = page['total']
                if not page['entities'] and len(rows) < total:
                    raise RuntimeError('Incomplete directory page')
                rows.extend(page['entities'])
        if len({r['id'] for r in rows}) != total:
            raise RuntimeError('Duplicate or missing directory IDs; rerun the check')
    else:
        rows = [dict(id=f'e-{i:05d}', kind=('people', 'companies', 'tools', 'pets', 'apps', 'games', 'topics')[i % 7],
                     label=hashlib.sha256(str(i // 7).encode()).hexdigest()[:16], profile={},
                     entries=[{'id': f'entry-{i}', 'source': 'notes'}]) for i in range(args.size)]
        # Several realistic duplicate buckets, including one larger than old caps.
        for i in range(0, min(len(rows), 700), 7):
            rows[i]['label'] = 'Shared identity candidate'
    from workflows.hfl.entity_candidates import CandidateIndex, candidates
    from workflows.hfl.entity_run_storage import write_run, read_run
    from workflows.hfl.entity_store import get_store
    result = {'mode': 'live-read-only' if args.live else 'synthetic', 'entities': len(rows),
              'types': dict(Counter(r['kind'] for r in rows)),
              'single_activity_entities': sum(len({e['id'] for e in r['entries']}) == 1 for r in rows)}
    with tempfile.TemporaryDirectory(prefix='harqis-entity-scale-') as temporary:
        os.environ['HARQIS_ENTITIES_DB'] = str(Path(temporary) / 'entities.sqlite3')
        started = time.perf_counter()
        index = CandidateIndex(rows, persistent=True)
        result['cold_index_seconds'] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        index = CandidateIndex(rows, persistent=True)
        result['warm_index_seconds'] = round(time.perf_counter() - started, 3)
        buckets = [v for (kind, key), v in index.postings.items() if key[0] == 'name' and len(v) > 1]
        result.update(exact_name_buckets=len(buckets), largest_exact_bucket=max(map(len, buckets), default=0))
        started = time.perf_counter()
        pairs = candidates(rows, index=index)
        result['candidate_seconds'] = round(time.perf_counter() - started, 3)
        result['candidate_pairs'] = len(pairs)
        if args.baseline_ref:
            # Run only code from the explicitly selected local repository revision.
            source = subprocess.run(['git', 'show', args.baseline_ref + ':workflows/hfl/entity_candidates.py'],
                                    check=True, capture_output=True, text=True).stdout
            namespace = {}
            exec(compile(source, '<candidate-baseline>', 'exec'), namespace)
            started = time.perf_counter()
            baseline = namespace['candidates'](rows)
            result['baseline_candidate_seconds'] = round(time.perf_counter() - started, 3)
            result['baseline_candidate_pairs'] = len(baseline)
            result['added_candidate_pairs'] = len(set(pairs) - set(baseline))
            result['removed_candidate_pairs'] = len(set(baseline) - set(pairs))
        # Exercise real full evidence payload sizes without persisting outside temp.
        run = {'id': 'benchmark', 'state': 'running', 'pairs': {
            str(i): {'id': str(i), 'state': 'pending', 'left': index.by_id[a], 'right': index.by_id[b]}
            for i, (a, b) in enumerate(pairs)}}
        result['legacy_json_bytes'] = len(json.dumps(run).encode())
        store = get_store()
        started = time.perf_counter()
        with store.connection() as db:
            write_run(db, run)
        result['initial_save_seconds'] = round(time.perf_counter() - started, 3)
        if pairs:
            run['pairs']['0']['state'] = 'deferred'
        started = time.perf_counter()
        with store.connection() as db:
            before = db.total_changes
            write_run(db, run)
            result['checkpoint_rows_written'] = db.total_changes - before
            result['stored_payload_bytes'] = db.execute('SELECT coalesce(sum(length(CAST(data AS BLOB))),0) FROM consolidation_pairs').fetchone()[0]
            result['stored_payload_bytes'] += db.execute('SELECT coalesce(sum(length(CAST(data AS BLOB))),0) FROM consolidation_evidence').fetchone()[0]
        result['checkpoint_seconds'] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        with store.connection() as db:
            restored = read_run(db, 'benchmark')
        result['load_seconds'] = round(time.perf_counter() - started, 3)
        assert restored['pairs'] == run['pairs']
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
