from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def management(monkeypatch, tmp_path):
    from hfl_api import app
    from modules.hfl_corpus import timeline
    from workflows.hfl.timeline_store import FollowUpStore
    store = FollowUpStore(tmp_path / "actions.sqlite3")
    monkeypatch.setattr(timeline, "store", lambda: store)
    monkeypatch.setattr(timeline, "write_completion", lambda *a, **kw: None)
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer frontend-test-hfl-api-token"
    yield client, store
    client.close()


def action(**fields):
    return {"request_id": str(uuid4()), "title": "Review capture", "expected_outcome": "Document findings", **fields}


def category(client):
    response = client.post("/api/hfl/categories", json={"name": "Project", "color": "#3b82f6", "instructions": "Keep evidence"})
    assert response.status_code == 201, response.text
    return response.json()["category"]


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/actions", None), ("post", "/actions", action()),
    ("get", "/actions/missing", None), ("patch", "/actions/missing", {"version": 1}),
    ("get", "/actions/missing/history", None),
    ("get", "/categories", None), ("post", "/categories", {"name": "A", "color": "#3b82f6"}),
    ("get", "/categories/1", None), ("patch", "/categories/1", {}), ("post", "/categories/1/archive", None),
    ("get", "/pins", None), ("post", "/pins", {}), ("get", "/pins/1", None),
    ("patch", "/pins/1", {}), ("delete", "/pins/1", None),
])
def test_every_management_route_requires_bearer(management, method, path, payload):
    client, _ = management
    client.headers.pop("Authorization")
    assert client.request(method, "/api/hfl" + path, json=payload).status_code == 401
    client.headers["Authorization"] = "Bearer wrong"
    assert client.request(method, "/api/hfl" + path, json=payload).status_code == 401


def test_action_retry_edits_conflicts_and_completion(management):
    client, store = management
    raw = action(prompt="Keep as intent", due_date=date.today().isoformat())
    first = client.post("/api/hfl/actions", json=raw)
    assert first.status_code == 201
    item = first.json()["item"]
    assert item["agent_enabled"] is False
    replay = client.post("/api/hfl/actions", json=raw)
    assert replay.status_code == 200 and replay.json()["duplicate"]
    assert replay.json()["item"]["id"] == item["id"]
    assert client.post("/api/hfl/actions", json={**raw, "title": "Other"}).status_code == 409
    url = "/api/hfl/actions/" + item["id"]
    assert client.get(url).json()["item"] == item
    assert client.get("/api/hfl/actions").json()["total"] == 1
    assert client.get("/api/hfl/actions?offset=1").json()["items"] == []
    edit = client.patch(url, json={"version": 1, "notes": "Notes", "due_date": ""})
    assert edit.status_code == 200
    assert edit.json()["item"]["prompt"] == raw["prompt"]
    assert edit.json()["item"]["due_date"] == ""
    assert client.patch(url, json={"version": 1, "status": "done"}).status_code == 409
    done = client.patch(url, json={"version": 2, "status": "done", "completion_note": "Reviewed"})
    assert done.status_code == 200
    assert done.json()["item"]["completed_at"]
    assert not done.json()["item"]["agent_enabled"]
    assert len(store.receipts()) == 1
    assert len(client.get(url + "/history").json()["history"]) == 3
    assert client.get("/api/hfl/actions?closed=true").json()["total"] == 1
    assert client.patch(url, json={"version": 3, "status": "dismissed"}).status_code == 200
    assert store.get(item["id"])["status"] == "dismissed"


@pytest.mark.parametrize("fields", [
    {"agent_enabled": True}, {"title": "  "}, {"request_id": "bad"},
    {"due_date": "2026-02-30"}, {"expected_outcome": ""},
])
def test_action_validation(management, fields):
    client, store = management
    assert client.post("/api/hfl/actions", json=action(**fields)).status_code == 422
    assert store.list() == []


def test_linked_action_validates_real_evidence_and_masks_secrets(management, monkeypatch, tmp_path):
    from modules.hfl_corpus import corpus, router
    document = tmp_path / "2026-09-14.md"
    document.write_text(
        "## 2026-09-14 09:00\nMoment: Visible\nEntry ID: hfl-visible\n\n"
        "## 2026-09-14 10:00\nMoment: Private\nEntry ID: hfl-private\nTags: #secrets\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus, "resolve_corpus_root", lambda: tmp_path)
    monkeypatch.setattr(router, "corpus_index", corpus.CorpusIndex(ttl_seconds=0))
    client, store = management
    source = {"path": document.name, "entry_id": "hfl-visible"}
    response = client.post("/api/hfl/actions", json=action(source=source))
    assert response.status_code == 201, response.text
    assert response.json()["item"]["source"]["title"] == "Visible"
    for guid in ("hfl-private", "hfl-missing"):
        assert client.post("/api/hfl/actions", json=action(source={**source, "entry_id": guid})).status_code == 404
    assert client.post("/api/hfl/actions", json=action(source={**source, "path": "../outside.md"})).status_code == 400
    assert len(store.list()) == 1


def test_category_lifecycle_and_partial_update(management):
    client, _ = management
    item = category(client)
    url = f"/api/hfl/categories/{item['id']}"
    assert client.get(url).json()["category"] == item
    changed = client.patch(url, json={"name": "Renamed"}).json()["category"]
    assert changed["instructions"] == "Keep evidence"
    assert changed["color"] == item["color"]
    assert client.post("/api/hfl/categories", json={"name": "renamed", "color": item["color"]}).status_code == 422
    assert client.patch(url, json={"color": "bad"}).status_code == 422
    assert client.patch(url, json={"instructions": None}).status_code == 422
    assert client.post(url + "/archive").status_code == 200
    snapshot = client.get("/api/hfl/categories").json()
    assert snapshot["categories"] == []
    assert snapshot["archived_categories"][0]["id"] == item["id"]
    assert client.get(url).json()["category"]["archived_at"]


def test_pin_lifecycle_preserves_fields_and_opt_out(management):
    client, _ = management
    cat = category(client)
    payload = {"category_id": cat["id"], "title": "Review week",
               "start_date": date.today().isoformat(), "end_date": date.today().isoformat(),
               "prompt": "Summarize the evidence"}
    response = client.post("/api/hfl/pins", json=payload)
    assert response.status_code == 201, response.text
    item = response.json()["pin"]
    url = f"/api/hfl/pins/{item['id']}"
    assert not item["agent_enabled"]
    assert client.get(url).json()["pin"] == item
    changed = client.patch(url, json={"note": "Updated"}).json()["pin"]
    assert changed["prompt"] == item["prompt"]
    assert not changed["agent_enabled"]
    assert client.patch(url, json={"agent_enabled": True}).status_code == 422
    assert len(client.get(f"/api/hfl/pins?category_id={item['category_id']}").json()["pins"]) == 1
    assert client.delete(url).json()["deleted"]
    assert client.get(url).status_code == 404
    assert client.delete(url).status_code == 404


def test_pin_bounds_normalization_and_archived_category(management, monkeypatch):
    from modules.hfl_corpus import management_api
    client, _ = management
    cat = category(client)
    today = date.today()
    raw = {"category_id": cat["id"], "title": "Range", "start_date": today.isoformat(), "end_date": (today - timedelta(days=1)).isoformat()}
    created = client.post("/api/hfl/pins", json=raw)
    assert created.status_code == 201
    assert created.json()["pin"]["start_date"] == raw["end_date"]
    assert client.post("/api/hfl/pins", json={**raw, "end_date": (today + timedelta(days=2200)).isoformat()}).status_code == 422
    assert client.post("/api/hfl/pins", json={**raw, "start_date": "bad"}).status_code == 422
    monkeypatch.setattr(management_api, "get_profile_store", lambda: SimpleNamespace(get=lambda: SimpleNamespace(birthdate=today.isoformat())))
    assert client.post("/api/hfl/pins", json=raw).status_code == 422
    client.post(f"/api/hfl/categories/{cat['id']}/archive")
    assert client.get("/api/hfl/pins").json()["pins"] == []
    assert client.post("/api/hfl/pins", json={**raw, "end_date": today.isoformat()}).status_code == 422


def test_missing_records_and_invalid_patch_leave_state_unchanged(management):
    client, store = management
    for path in ("actions/missing", "categories/999", "pins/999"):
        assert client.get("/api/hfl/" + path).status_code == 404
        assert client.patch("/api/hfl/" + path, json={"version": 1} if path.startswith("actions") else {}).status_code == 404
    item = client.post("/api/hfl/actions", json=action()).json()["item"]
    url = "/api/hfl/actions/" + item["id"]
    for changes in ({"notes": None}, {"agent_enabled": True}, {"source": {}}, {"status": "invalid"}):
        assert client.patch(url, json={"version": 1, **changes}).status_code == 422
    assert store.get(item["id"])["version"] == 1
