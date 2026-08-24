from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _clean_second_brain_store():
    from modules.second_brain.service import get_second_brain_store

    store = get_second_brain_store()
    with store._connect() as connection:
        for table in (
            "context_events",
            "manual_overrides",
            "mode_decisions",
            "workflow_runs",
            "feed_items",
            "feed_revisions",
        ):
            connection.execute(f"DELETE FROM {table}")
    yield


def test__second_brain_page_requires_authentication():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        response = client.get("/second-brain", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test__second_brain_page_renders_empty_guidance(authenticated_client):
    response = authenticated_client.get("/second-brain")
    assert response.status_code == 200
    assert "What matters now" in response.text
    assert "No advisory items yet" in response.text
    assert "Web feed" in response.text


def test__second_brain_mode_override_is_expiring(authenticated_client, monkeypatch):
    from modules.second_brain import router

    monkeypatch.setattr(router, "_dispatch_reconcile", lambda correlation_id: "task-1")
    response = authenticated_client.post(
        "/second-brain/mode",
        data={"modes": "work+finance", "duration_minutes": "120"},
    )
    assert response.status_code == 200
    payload = authenticated_client.get("/second-brain/api/feed").json()
    assert payload["override"]["modes"] == ["work", "finance"]


def test__second_brain_settings_keep_optional_clients_off_by_default(authenticated_client):
    payload = authenticated_client.get("/second-brain/api/feed").json()
    assert payload["config"]["clients"] == {
        "web": True,
        "telegram": False,
        "rainmeter": False,
        "cli": False,
    }
    disabled = authenticated_client.get("/second-brain/api/feed?client=cli")
    assert disabled.status_code == 403


def test__second_brain_command_records_typed_context(authenticated_client, monkeypatch):
    from modules.second_brain import router
    from modules.second_brain.service import get_second_brain_store

    monkeypatch.setattr(router, "_dispatch_reconcile", lambda correlation_id: "task-2")
    response = authenticated_client.post(
        "/second-brain/api/commands",
        content=json.dumps({"command": "Review my current Jira work"}),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 202
    events = get_second_brain_store().recent_context()
    assert events[0]["event_type"] == "text_command"
    assert events[0]["payload"]["text"] == "Review my current Jira work"
