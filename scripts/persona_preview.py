"""Run an isolated review instance: python scripts/persona_preview.py frontend|worker [--port 8093]."""
import argparse
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def bootstrap(port):
    os.chdir(ROOT)
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    sys.path.insert(0, str(ROOT / 'frontend'))
    from config import get_settings
    original = Path(get_settings().profile_store_path).expanduser().resolve()
    data = ROOT / '.harqis-data' / 'persona-preview'
    data.mkdir(parents=True, exist_ok=True)
    profile = data / 'profile.sqlite3'
    if not profile.exists() and original.is_file():
        with sqlite3.connect(f'{original.as_uri()}?mode=ro', uri=True) as source, sqlite3.connect(profile) as target:
            source.backup(target)
    os.environ.update({
        'HARQIS_DATA_ROOT': str(data), 'PROFILE_STORE_PATH': str(profile),
        'HFL_SHARE_STORE_PATH': str(data / 'shares.sqlite3'),
        'SECOND_BRAIN_STORE_PATH': str(data / 'second-brain.sqlite3'),
        'HFL_TIMELINE_STORE_PATH': str(data / 'timeline.sqlite3'),
        'HFL_AGENT_BRIDGE_STORE_PATH': str(data / 'agent-bridge.sqlite3'),
        'HARQIS_ENTITIES_DB': str(data / 'entities.sqlite3'),
        'HFL_PERSONA_API_URL': f'http://127.0.0.1:{port}',
        'HFL_PERSONA_QUEUE': 'persona-preview.host', 'HARQIS_QUEUE_PREFIX': 'persona-preview',
        'HFL_SHARE_PUBLIC_URL': f'http://127.0.0.1:{port}', 'BEHIND_PROXY': 'false',
        'HFL_TIMELINE_LOCAL_PREVIEW': '1',
    })
    get_settings.cache_clear()
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['frontend', 'worker'])
    parser.add_argument('--port', type=int, default=8093)
    args = parser.parse_args()
    bootstrap(args.port)
    if args.command == 'frontend':
        import uvicorn
        uvicorn.run('main:app', host='127.0.0.1', port=args.port)
    else:
        from core.apps.sprout.app.celery import SPROUT
        import workflows.hfl
        SPROUT.worker_main(['worker', '--pool=solo', '--concurrency=1', '--queues=persona-preview.host',
                           '--hostname=persona-preview@%h', '--loglevel=WARNING'])


if __name__ == '__main__':
    main()
