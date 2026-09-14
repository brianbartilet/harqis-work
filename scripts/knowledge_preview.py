"""Launch isolated Activity Corpus entities: python scripts/knowledge_preview.py frontend|worker|refresh.

Uses the existing machine bootstrap, followed by explicit preview overrides.
No Beat process is started. Credentials remain in the gitignored environment.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def bootstrap():
    os.chdir(REPO_ROOT)
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(REPO_ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    data = Path(os.environ.get('HARQIS_CONNECTED_PREVIEW_ROOT', REPO_ROOT / '.harqis-data' / 'connected-preview')).resolve()
    data.mkdir(parents=True, exist_ok=True)
    config = data / 'preview-env.json'
    if config.exists():
        os.environ.update(json.loads(config.read_text('utf-8')))
    else:
        os.environ['HARQIS_CONNECTED_SOURCE_URL'] = os.environ.get('HFL_CORPUS_API_URL', '')
        os.environ['HARQIS_CONNECTED_SOURCE_TOKEN'] = os.environ.get('HFL_CORPUS_API_TOKEN', '')
    os.environ.update({
        'HARQIS_CONNECTED_PREVIEW': '1', 'HARQIS_DATA_ROOT': str(data),
        'HARQIS_CONNECTED_WEB_URL': 'http://127.0.0.1:8092',
        'HARQIS_ENTITIES_DB': str(data / 'corpus-entities.sqlite3'),
        'HARQIS_ENTITIES_QUEUE': 'connected-preview.adhoc',
        'HARQIS_OBSIDIAN_VAULT': str(data / 'HARQIS Knowledge Preview'),
        'HFL_CORPUS_API_URL': os.environ.get('HARQIS_CONNECTED_SOURCE_URL', ''),
        'HFL_CORPUS_API_TOKEN': os.environ.get('HARQIS_CONNECTED_SOURCE_TOKEN', ''),
        'PROFILE_STORE_PATH': str(data / 'profile.sqlite3'),
        'SECOND_BRAIN_STORE_PATH': str(data / 'second-brain.sqlite3'),
        'HFL_SHARE_STORE_PATH': str(data / 'shares.sqlite3'),
        'HFL_TIMELINE_STORE_PATH': str(data / 'timeline.sqlite3'),
        'HFL_AGENT_BRIDGE_STORE_PATH': str(data / 'agent-bridge.sqlite3'),
        'HFL_TIMELINE_LOCAL_PREVIEW': '1',
        'HARQIS_QUEUE_PREFIX': 'connected-preview', 'HARQIS_CONNECTED_QUEUE': 'adhoc', 'BEHIND_PROXY': 'false',
    })
    sys.path.insert(0, str(REPO_ROOT / 'frontend'))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['frontend', 'worker', 'refresh'])
    parser.add_argument('--port', type=int, default=8092)
    args = parser.parse_args()
    bootstrap()
    os.environ['HARQIS_CONNECTED_WEB_URL'] = f'http://127.0.0.1:{args.port}'
    if args.command == 'frontend':
        import uvicorn
        uvicorn.run('main:app', host='127.0.0.1', port=args.port)
    elif args.command == 'worker':
        from core.apps.sprout.app.celery import SPROUT
        import workflows.knowledge
        SPROUT.worker_main(['worker', '--pool=solo', '--concurrency=1',
                            '--queues=connected-preview.adhoc', '--hostname=connected-preview@%h', '--loglevel=WARNING'])
    else:
        from workflows.hfl.entity_events import request_enrichment
        result = request_enrichment()
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
