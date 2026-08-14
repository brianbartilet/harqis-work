from __future__ import annotations

import os
import sys
import tempfile
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
os.environ["HFL_SHARE_SECRET_KEY"] = "frontend-test-share-secret-key"
os.environ["HFL_SHARE_PUBLIC_URL"] = "https://share.example.test"
os.environ["HFL_SHARE_LIVE_REFRESH_SECONDS"] = "0"
os.environ["HFL_SHARE_SESSION_TTL_SECONDS"] = "21600"
os.environ["HFL_SHARE_MAX_CONCURRENT_SESSIONS"] = "20"
os.environ["HFL_SHARE_CAPACITY_RETRY_SECONDS"] = "300"
os.environ["BEHIND_PROXY"] = "false"
os.environ["HFL_SHARE_STORE_PATH"] = str(
    Path(tempfile.gettempdir())
    / f"harqis-frontend-shares-{os.getpid()}.sqlite3"
)
os.environ["PROFILE_STORE_PATH"] = str(
    Path(tempfile.gettempdir())
    / f"harqis-frontend-profile-{os.getpid()}.sqlite3"
)


@pytest.fixture(autouse=True)
def _empty_owner_profile():
    from modules.profile.store import get_profile_store

    store = get_profile_store()
    with store._connect() as connection:
        connection.execute("DELETE FROM owner_profile")
    yield
    with store._connect() as connection:
        connection.execute("DELETE FROM owner_profile")


@pytest.fixture
def authenticated_client():
    from auth import create_session_token
    from main import app

    with TestClient(app) as client:
        client.cookies.set("session", create_session_token("frontend-test-user"))
        yield client
