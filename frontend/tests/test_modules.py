from modules.registry import MODULES, module_by_key


def test_module_registry_has_fixed_primary_navigation():
    assert [module.key for module in MODULES] == [
        "home", "workflows", "applications", "hfl_corpus"
    ]
    assert module_by_key("hfl_corpus").route == "/hfl-corpus"


def test_module_pages_require_authentication():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        for route in ("/home", "/workflows", "/applications", "/hfl-corpus"):
            response = client.get(route, follow_redirects=False)
            assert response.status_code == 302
            assert response.headers["location"] == "/login"


def test_home_renders_manifesto_and_navigation(authenticated_client):
    response = authenticated_client.get("/home")

    assert response.status_code == 200
    assert "HARQIS Work Manifesto" in response.text
    assert "Workflows" in response.text
    assert "Apps" in response.text
    assert "HFL Corpus" in response.text


def test_legacy_dashboard_redirects_to_home(authenticated_client):
    response = authenticated_client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/home"


def test_workflows_module_preserves_reorderable_subtabs(authenticated_client):
    response = authenticated_client.get("/workflows")

    assert response.status_code == 200
    assert 'data-sortable-tabs' in response.text
    assert "harqis_tab_order" in response.text
    assert "Edit Layout" in response.text
    assert "Automation inventory" in response.text
    assert "automations across" in response.text
    assert "border-blue-500 text-blue-400" in response.text


def test_workflow_trigger_preserves_existing_dispatch_endpoint(
    authenticated_client, monkeypatch
):
    import modules.workflows.router as workflow_routes

    monkeypatch.setattr(
        workflow_routes,
        "find_task",
        lambda workflow, task_key: {
            "task_path": "example.task",
            "queue": "default",
            "kwargs": {"sample": True},
        },
    )
    monkeypatch.setattr(
        workflow_routes.celery_client,
        "dispatch",
        lambda **kwargs: "local-test-task-id",
    )

    response = authenticated_client.post("/tasks/example/example/trigger")

    assert response.status_code == 200
    assert "local-test-task-id" in response.text
    assert "Pending" in response.text


def test_hfl_corpus_module_renders_an_empty_index(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: ())

    response = authenticated_client.get("/hfl-corpus")

    assert response.status_code == 200
    assert "HFL Corpus" in response.text
    assert "0 Markdown files" in response.text
