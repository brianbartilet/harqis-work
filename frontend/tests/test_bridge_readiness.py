"""Use the worker router without app startup or mutable store fixtures."""
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize('token,header,expected', [
    ('test-secret', 'Bearer test-secret', 200),
    ('test-secret', 'Bearer wrong-secret', 401),
    ('test-secret', '', 401),
    ('', 'Bearer test-secret', 503),
])
def test_readiness_auth_without_storage(monkeypatch, token, header, expected):
    from modules.hfl_corpus import agent_bridge
    app = FastAPI()
    app.include_router(agent_bridge.worker_router)
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', token)
    def forbidden(*args, **kwargs):
        raise AssertionError('Readiness must not access or mutate task/settings storage')
    # Scope patches to requests; conftest's isolated store teardown remains usable.
    with monkeypatch.context() as patch:
        for name in ('bridge_store', 'read_settings', 'reconcile_runs', 'sweep', 'deliver_pending', 'apply_action', 'accept'):
            patch.setattr(agent_bridge, name, forbidden)
        patch.setattr(sqlite3, 'connect', forbidden)
        patch.setattr(Path, 'mkdir', forbidden)
        with TestClient(app) as client:
            for _ in range(2):
                response = client.get('/api/hfl-agent/ready', headers={'Authorization': header})
                assert response.status_code == expected
                if expected == 200:
                    assert response.json() == {'status': 'ok', 'service': 'hfl-agent-bridge'}
                assert 'test-secret' not in response.text
