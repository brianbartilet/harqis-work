"""Run a mock-only Fleet instance: python scripts/n8n_preview.py --port 8094."""
import argparse
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def bootstrap():
    os.chdir(ROOT)
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    load_env_into_os()
    os.environ.setdefault('APP_CONFIG_FILE', str(ROOT / 'apps_config.yaml'))
    os.environ.setdefault('WORKFLOW_CONFIG', 'workflows.config')
    os.environ.update(machine_env_vars(load_machine_config(None)))
    data = ROOT / '.harqis-data' / 'n8n-fleet-preview'
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        'HARQIS_DATA_ROOT': str(data), 'HFL_TIMELINE_LOCAL_PREVIEW': '1', 'HARQIS_N8N_MOCK': '1', 'HARQIS_NOD_MOCK': '1',
        'HFL_CORPUS_API_URL': '', 'HFL_CORPUS_API_TOKEN': '', 'BEHIND_PROXY': 'false',
        'APP_USERNAME': 'preview', 'APP_PASSWORD': secrets.token_urlsafe(24), 'APP_SECRET_KEY': secrets.token_urlsafe(32),
        'PROFILE_STORE_PATH': str(data / 'profile.sqlite3'), 'HARQIS_AGENTS_DB': str(data / 'fleet.sqlite3'),
        'HARQIS_CONNECTORS_DB': str(data / 'connectors.sqlite3'), 'HARQIS_ENTITIES_DB': str(data / 'entities.sqlite3'),
        'HFL_SHARE_STORE_PATH': str(data / 'shares.sqlite3'), 'SECOND_BRAIN_STORE_PATH': str(data / 'brain.sqlite3'),
        'HFL_TIMELINE_STORE_PATH': str(data / 'timeline.sqlite3'), 'HFL_AGENT_BRIDGE_STORE_PATH': str(data / 'bridge.sqlite3'),
        'HFL_SESSION_AUDIT_PATH': str(data / 'audit'), 'HFL_CORPUS_PATH': str(data / 'corpus'),
    })
    (data / 'corpus').mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT / 'frontend'))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8094)
    args = parser.parse_args()
    bootstrap()
    from modules.integrations.n8n_fleet import link, refresh
    from modules.agents.service import defaults
    linked = link('preview', {'remote_id': 'atlas', 'profile': {**defaults('Atlas · HARQIS Operations'), 'runtime': 'n8n', 'classification': 'workflows', 'description': 'Mock n8n agent · workflow discovery, dependencies and execution history.'}})
    refresh('preview', linked['item']['id'])
    from modules.integrations.nod import link as link_nod
    nod_agent = link_nod('preview', {'profile': {**defaults('Nod · HARQIS Assistant'), 'runtime': 'nod'}})['item']
    from main import app
    from fastapi.responses import RedirectResponse, JSONResponse
    from auth import create_session_token
    @app.middleware('http')
    async def mock_credentials_only(request, call_next):
        if request.method != 'GET' and request.url.path.startswith('/integrations/api/connectors/'):
            return JSONResponse({'detail': 'This preview uses a mock connector. Live credentials cannot be tested or saved here.'}, status_code=409)
        return await call_next(request)
    @app.get('/preview-login', include_in_schema=False)
    def login():
        response = RedirectResponse('/agents?agent=' + linked['item']['id'])
        response.set_cookie('session', create_session_token('preview'), httponly=True, samesite='lax')
        return response
    @app.get('/preview-nod', include_in_schema=False)
    def nod_login():
        response = RedirectResponse('/agents?agent=' + nod_agent['id'])
        response.set_cookie('session', create_session_token('preview'), httponly=True, samesite='lax')
        return response
    import uvicorn
    # This standalone app is loopback only, with no scheduler or worker.
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
