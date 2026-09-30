"""Initialize or inspect catalog readiness using the repository environment."""
import argparse
import json
import os


def main():
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', 'apps_config.yaml')
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'check'])
    args = parser.parse_args()
    from apps.file_index.store import Store
    from apps.file_index.adapters import host_id
    store = Store()
    with store.connect() as db:
        integrity = db.execute('PRAGMA quick_check').fetchone()[0]
        version = db.execute('PRAGMA user_version').fetchone()[0]
    result = {'schema_version': version, 'integrity': integrity,
              'database': str(store.path), 'host_id': host_id(),
              'files': store.catalog(limit=1)['total'], 'sources': len(store.all('sources')),
              'queue': os.environ.get('FILES_QUEUE', 'files'),
              'beat_enabled': os.environ.get('FILES_ENABLED', '').lower() in {'1', 'true', 'yes'},
              'public_url_configured': bool(os.environ.get('FILES_PUBLIC_URL'))}
    if args.command == 'check':
        result['allowed_roots_configured'] = bool(json.loads(os.environ.get('FILES_ALLOWED_ROOTS', '[]')))
        result['sftp_profiles_configured'] = bool(os.environ.get('FILES_SFTP_PROFILES_PATH'))
    print(json.dumps(result, indent=2))
    return 0 if integrity == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
