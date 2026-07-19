from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))

# Test-only values prevent imports from depending on deploy secrets. They exist
# only inside the pytest process and are never written to an env file.
os.environ["APP_USERNAME"] = "frontend-test-user"
os.environ["APP_PASSWORD"] = "frontend-test-password"
os.environ["APP_SECRET_KEY"] = "frontend-test-secret-key-32-characters"
os.environ["HFL_CORPUS_API_TOKEN"] = "frontend-test-hfl-api-token"
os.environ["HFL_CORPUS_API_URL"] = ""


@pytest.fixture
def authenticated_client():
    from auth import create_session_token
    from main import app

    with TestClient(app) as client:
        client.cookies.set("session", create_session_token("frontend-test-user"))
        yield client
