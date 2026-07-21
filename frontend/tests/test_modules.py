from modules.registry import MODULES, module_by_key


def test_module_registry_has_fixed_primary_navigation():
    assert [module.key for module in MODULES] == [
        "home", "manifesto", "workflows", "applications", "hfl_corpus"
    ]
    manifesto = module_by_key("manifesto")
    assert manifesto is not None
    assert manifesto.route == "/manifesto"
    assert module_by_key("hfl_corpus").route == "/hfl-corpus"


def test_module_pages_require_authentication():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        for route in (
            "/home", "/manifesto", "/workflows", "/applications", "/hfl-corpus"
        ):
            response = client.get(route, follow_redirects=False)
            assert response.status_code == 302
            assert response.headers["location"] == "/login"


def test_home_renders_module_navigation_without_manifesto(authenticated_client):
    response = authenticated_client.get("/home")

    assert response.status_code == 200
    assert "Heuristic Automation for a Reliable Quality Integration System" in response.text
    assert "Hopefully another rather quite intelligent system" in response.text
    assert "A self-hosted second brain" in response.text
    assert 'id="platform-modules-heading"' in response.text
    assert "Platform Modules" in response.text
    assert "HARQIS Work Manifesto" not in response.text
    assert 'href="/manifesto"' in response.text
    assert "Workflows" in response.text
    assert "Apps" in response.text
    assert "Activity Corpus" in response.text
    assert "based on Homework for Life" in response.text


def test_manifesto_module_renders_guiding_principles(authenticated_client):
    response = authenticated_client.get("/manifesto")

    assert response.status_code == 200
    assert "Guiding principles" in response.text
    assert "HARQIS Work Manifesto" in response.text
    assert 'class="rounded-md px-3 py-1.5 text-xs font-medium transition' in response.text
    assert 'href="/manifesto"' in response.text


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
    assert "Activity Corpus" in response.text
    assert "HARQIS ACTIVITY LOGS" in response.text
    assert "0 files" in response.text
