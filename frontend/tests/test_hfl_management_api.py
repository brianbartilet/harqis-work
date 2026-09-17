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


def test_mcp_service_requests_round_trip_through_standalone_api(management, monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from apps.hfl_corpus import mcp as adapter
    from apps.hfl_corpus.references.web.api.management import ApiServiceHflCorpusManagement
    from tools.catalog import is_write_tool

    client, _ = management
    responses = []

    def service(config):
        result = ApiServiceHflCorpusManagement(config, api_url="http://testserver", api_key="frontend-test-hfl-api-token")

        def execute(request):
            method = request.get_request_method()
            method = getattr(method, "value", method)
            response = client.request(method, "/api/hfl/" + request.get_full_url().lstrip("/"),
                                      params=request.get_query_strings(), **(request.get_body() or {}))
            assert response.status_code < 400, response.text
            responses.append(response)
            return SimpleNamespace(data=response.json())

        monkeypatch.setattr(result.client, "execute_request", execute)
        return result

    monkeypatch.setattr(adapter, "ApiServiceHflCorpusManagement", service)
    mcp = FastMCP("management-test")
    adapter.register_hfl_corpus_tools(mcp)

    def call(tool_name, **kwargs):
        return mcp._tool_manager._tools[tool_name].fn(**kwargs)

    item = call("create_hfl_corpus_action", **action(prompt="Save for later"))["item"]
    assert not item["agent_enabled"]
    assert call("get_hfl_corpus_action", action_id=item["id"])["item"] == item
    assert call("list_hfl_corpus_actions")["total"] == 1
    updated = call("update_hfl_corpus_action", action_id=item["id"], version=1, changes={"notes": "Revised"})
    assert updated["item"]["notes"] == "Revised"
    assert len(call("get_hfl_corpus_action_history", action_id=item["id"])["history"]) == 2
    cat = call("create_hfl_corpus_category", name="Tool category", color="#3b82f6")["category"]
    assert call("list_hfl_corpus_categories")["categories"] == [cat]
    assert call("get_hfl_corpus_category", category_id=cat["id"])["category"] == cat
    assert call("update_hfl_corpus_category", category_id=cat["id"], changes={"instructions": "Guidance"})["category"]["instructions"] == "Guidance"
    pin = call("create_hfl_corpus_pin", category_id=cat["id"], start_date=date.today().isoformat(),
               end_date=date.today().isoformat(), title="Tool pin", prompt="Saved prompt")["pin"]
    assert not pin["agent_enabled"]
    assert call("get_hfl_corpus_pin", pin_id=pin["id"])["pin"] == pin
    assert call("list_hfl_corpus_pins", category_id=cat["id"])["pins"] == [pin]
    assert call("update_hfl_corpus_pin", pin_id=pin["id"], changes={"note": "More context"})["pin"]["note"] == "More context"
    assert call("delete_hfl_corpus_pin", pin_id=pin["id"])["deleted"]
    assert call("archive_hfl_corpus_category", category_id=cat["id"])["category"]["archived_at"]
    assert len(responses) == 15
    for name in mcp._tool_manager._tools:
        if name.startswith(("create_", "update_", "delete_", "archive_")):
            assert is_write_tool(name), name


@pytest.mark.parametrize('resource', ['actions', 'pins'])
def test_input_attachments_upload_retry_detach_and_isolation(management, resource):
    client, _ = management
    if resource == 'actions':
        item = client.post('/api/hfl/actions', json=action()).json()['item']
    else:
        item = client.post('/api/hfl/pins', json={'category_id': category(client)['id'],
            'start_date': date.today().isoformat(), 'end_date': date.today().isoformat(), 'title': 'Pin'}).json()['pin']
    url = f"/api/hfl/{resource}/{item['id']}/attachments"
    files = [('files', ('brief.md', b'# Brief\nUse the supplied link')), ('files', ('data.csv', b'x,y\n1,2'))]
    uploaded = client.post(url, files=files)
    assert uploaded.status_code == 200, uploaded.text
    rows = uploaded.json()['attachments']
    assert len(rows) == 2
    assert client.post(url, files=files).json()['attachments'] == rows
    assert client.get(url).json()['attachments'] == rows
    download = client.get(url + '/' + rows[0]['id'])
    assert download.content == files[0][1][1]
    assert download.headers['content-type'] == 'application/octet-stream'
    assert 'attachment;' in download.headers['content-disposition']
    assert client.get(f"/api/hfl/{resource}/other/attachments/{rows[0]['id']}").status_code == 404
    assert len(client.delete(url + '/' + rows[0]['id']).json()['attachments']) == 1
    assert client.get(url + '/' + rows[0]['id']).content == files[0][1][1]
    client.headers.pop('Authorization')
    for method, path in [('GET', url), ('POST', url), ('DELETE', url + '/' + rows[1]['id']), ('GET', url + '/' + rows[1]['id'])]:
        assert client.request(method, path).status_code == 401


def test_attachment_limits_are_atomic_and_filenames_are_safe(management, monkeypatch):
    from modules.hfl_corpus import attachments
    client, actions = management
    item = client.post('/api/hfl/actions', json=action()).json()['item']
    url = f"/api/hfl/actions/{item['id']}/attachments"
    monkeypatch.setattr(attachments, 'MAX_FILE_BYTES', 5)
    response = client.post(url, files=[('files', ('good.txt', b'good')), ('files', ('big.txt', b'123456'))])
    assert response.status_code == 413
    assert client.get(url).json()['attachments'] == []
    assert not list(actions.path.with_suffix('.inputs').glob('.upload-*'))
    row = client.post(url, files=[('files', ('../../outside.html', b'hello'))]).json()['attachments'][0]
    assert row['name'] == 'outside.html'
    assert '/' not in row['filename'] and row['filename'].endswith('.html')
    assert client.get(url + '/' + row['id']).headers['x-content-type-options'] == 'nosniff'
    monkeypatch.setattr(attachments, 'MAX_FILES', 1)
    assert client.post(url, files=[('files', ('other.txt', b'good'))]).status_code == 413
    assert len(client.get(url).json()['attachments']) == 1


def test_attachment_service_and_mcp_transport(management, monkeypatch, tmp_path):
    from apps.hfl_corpus import mcp as adapter
    from apps.hfl_corpus.references.web.api.management import ApiServiceHflCorpusManagement
    from mcp.server.fastmcp import FastMCP
    from tools.catalog import is_write_tool
    client, _ = management
    item = client.post('/api/hfl/actions', json=action()).json()['item']
    source = tmp_path / 'brief.md'; source.write_text('Read this briefing', encoding='utf-8')

    def service(config):
        instance = ApiServiceHflCorpusManagement(config, api_url='http://testserver', api_key='test-token')
        def request(method, path, **kwargs):
            response = client.request(method, '/api/hfl/' + path, **kwargs)
            response.raise_for_status()
            return response
        monkeypatch.setattr(instance, '_raw_request', request)
        return instance
    monkeypatch.setattr(adapter, 'ApiServiceHflCorpusManagement', service)
    server = FastMCP('attachment-test'); adapter.register_hfl_corpus_tools(server)
    invoke = lambda name, **kwargs: server._tool_manager._tools[name].fn(**kwargs)
    args = {'resource': 'actions', 'source_id': item['id']}
    rows = invoke('upload_hfl_corpus_attachments', **args, file_paths=[str(source)])['attachments']
    assert invoke('list_hfl_corpus_attachments', **args)['attachments'] == rows
    output = tmp_path / 'download.md'
    invoke('download_hfl_corpus_attachment', **args, attachment_id=rows[0]['id'], destination=str(output))
    assert output.read_bytes() == source.read_bytes()
    assert is_write_tool('download_hfl_corpus_attachment')
    assert invoke('delete_hfl_corpus_attachment', **args, attachment_id=rows[0]['id'])['attachments'] == []


def test_management_agents_can_create_and_reprioritize_actions(management):
    client, store = management
    response = client.post('/api/hfl/actions', json=action(matrix='Q2', matrix_confidence='medium', matrix_reason='Long-term owner goal'))
    assert response.status_code == 201
    item = response.json()['item']
    assert item['matrix'] == 'Q2' and item['agent_enabled'] is False
    response = client.patch('/api/hfl/actions/'+item['id'], json={'version':1, 'matrix':'Q1', 'matrix_confidence':'high', 'matrix_reason':'Owner supplied a deadline'})
    assert response.status_code == 200
    assert response.json()['item']['matrix'] == 'Q1'
    assert client.patch('/api/hfl/actions/'+item['id'], json={'version':2,'matrix':'Q5'}).status_code == 422
