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
            "chat_messages",
            "config_versions",
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
    assert "Your adaptive briefing" in response.text
    assert "Your briefing is assembling" in response.text
    assert "Second Brain live context" in response.text


def test__second_brain_places_collapsed_controls_before_ticker(authenticated_client):
    response = authenticated_client.get("/second-brain")
    assert response.status_code == 200
    controls_at = response.text.index('data-controls-panel')
    ticker_at = response.text.index('data-ticker-track')
    assert controls_at < ticker_at
    assert '<details id="brain-controls-panel"' in response.text
    assert '<details id="brain-controls-panel" open' not in response.text
    assert "requestAnimationFrame(frame)" in response.text
    assert "speed=12" in response.text


def test__second_brain_mode_override_is_expiring(authenticated_client, monkeypatch):
    from modules.second_brain import router

    monkeypatch.setattr(router, "_dispatch_reconcile", lambda correlation_id: "task-1")
    response = authenticated_client.post(
        "/second-brain/mode",
        data={"modes": "default", "duration_minutes": "120"},
    )
    assert response.status_code == 200
    payload = authenticated_client.get("/second-brain/api/feed").json()
    assert payload["override"]["modes"] == ["default"]


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


def test__second_brain_category_settings_are_configurable(authenticated_client, monkeypatch):
    from modules.second_brain import router

    monkeypatch.setattr(router, "_dispatch_reconcile", lambda correlation_id: "task-category")
    response = authenticated_client.post(
        "/second-brain/categories",
        data={
            "mode_id": "tabletop",
            "name": "Tabletop Lab",
            "color": "#a78bfa",
            "enabled": "on",
            "keywords": "mtg, deck",
            "refresh_minutes": "30",
            "client_eligibility": "web,telegram",
            "fallback_start": "18:00",
            "fallback_end": "23:30",
        },
    )
    assert response.status_code == 200
    modes = {mode["mode_id"]: mode for mode in authenticated_client.get("/second-brain/api/feed").json()["modes"]}
    assert modes["tabletop"]["keywords"] == ["mtg", "deck"]
    assert modes["tabletop"]["client_eligibility"] == ["web", "telegram"]
    assert modes["tabletop"]["fallback_windows"][0]["start"] == "18:00"


def test__second_brain_feed_accepts_scoped_api_bearer(authenticated_client, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_API_TOKEN", "test-second-brain-token")
    authenticated_client.cookies.clear()
    response = authenticated_client.get(
        "/second-brain/api/feed?client=cli",
        headers={"Authorization": "Bearer test-second-brain-token"},
    )
    assert response.status_code == 403  # client remains opt-in

    from modules.second_brain.service import get_second_brain_store

    store = get_second_brain_store()
    store.save_config(
        {"clients": {"web": True, "telegram": False, "rainmeter": False, "cli": True}}
    )
    store.append_chat(role="user", content="private advisory context", correlation_id="chat-private")
    response = authenticated_client.get(
        "/second-brain/api/feed?client=cli",
        headers={"Authorization": "Bearer test-second-brain-token"},
    )
    assert response.status_code == 200
    assert "chat" not in response.json()
    full_detail = authenticated_client.get(
        "/second-brain/api/feed?client=web",
        headers={"Authorization": "Bearer test-second-brain-token"},
    )
    assert full_detail.status_code == 403


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
