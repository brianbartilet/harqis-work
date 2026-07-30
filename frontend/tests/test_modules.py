import re

from modules.registry import MODULES, PRIMARY_MODULES, module_by_key


def test_module_shell_uses_versioned_self_hosted_assets(authenticated_client):
    response = authenticated_client.get("/home")

    assert response.status_code == 200
    for external_origin in (
        "cdn.tailwindcss.com",
        "unpkg.com",
        "cdn.jsdelivr.net",
    ):
        assert external_origin not in response.text

    asset_urls = re.findall(
        r'(?:href|src)="(/static/(?:css|vendor)/[^"?]+\?v=[0-9a-f]{12})"',
        response.text,
    )
    assert len(asset_urls) == 4

    for asset_url in asset_urls:
        asset_response = authenticated_client.get(asset_url)
        assert asset_response.status_code == 200
        assert asset_response.headers["cache-control"] == (
            "public, max-age=31536000, immutable"
        )


def test_authenticated_module_pages_are_not_edge_cacheable(authenticated_client):
    response = authenticated_client.get("/home")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_dynamic_routes_cannot_override_no_store(authenticated_client):
    from fastapi.responses import Response
    from main import app

    @app.get("/_test/cacheable-dynamic")
    async def cacheable_dynamic_response():
        return Response(headers={"Cache-Control": "public, max-age=60"})

    response = authenticated_client.get("/_test/cacheable-dynamic")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_missing_static_assets_are_not_immutable(authenticated_client):
    response = authenticated_client.get("/static/missing-asset.js")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


def test_module_registry_has_fixed_primary_navigation():
    assert [module.key for module in MODULES] == [
        "home",
        "hfl_corpus",
        "sharing",
        "manifesto",
        "workflows",
        "applications",
    ]
    manifesto = module_by_key("manifesto")
    assert manifesto is not None
    assert manifesto.route == "/manifesto"
    assert module_by_key("hfl_corpus").route == "/hfl-corpus"
    assert module_by_key("sharing").label == "Share Corpus"
    assert "manifesto" not in {module.key for module in PRIMARY_MODULES}
    assert "home" not in {module.key for module in PRIMARY_MODULES}


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


def test_home_renders_dedicated_manifesto_section_outside_platform_modules(
    authenticated_client,
):
    response = authenticated_client.get("/home")

    assert response.status_code == 200
    assert "Heuristic Automation for Resilient, Queryable Integration Systems" in response.text
    assert "The HARQIS operating loop" in response.text
    assert "Turn lived activity into reliable action." in response.text
    assert 'id="platform-modules-heading"' in response.text
    assert "Platform modules" in response.text
    assert 'id="signal-path-heading"' in response.text
    assert "From evidence to expression" in response.text
    for stage in ("Capture", "Organize", "Distill", "Orchestrate", "Express"):
        assert stage in response.text
    assert 'id="manifesto-heading"' in response.text
    assert "HARQIS Work Manifesto" in response.text
    assert "The framework behind the platform" in response.text
    assert "Read the Manifesto" in response.text
    assert 'href="/manifesto"' in response.text
    primary_navs = re.findall(
        r'<nav aria-label="Primary navigation"[^>]*>(.*?)</nav>',
        response.text,
        re.DOTALL,
    )
    assert len(primary_navs) == 2
    desktop_nav, mobile_nav = primary_navs
    assert "Manifesto" not in desktop_nav
    assert "Manifesto" not in mobile_nav
    assert "Workflows" in response.text
    assert "Apps" in response.text
    assert "Activity Corpus" in response.text
    assert "based on Homework for Life" in response.text
    assert 'aria-label="HARQIS home"' in response.text
    assert 'aria-label="Primary navigation"' in response.text
    assert 'aria-current="page"' not in response.text
    assert '<main class="mx-auto max-w-6xl' in response.text
    assert "grid grid-cols-1 md:grid-cols-2" in response.text
    assert 'class="rounded-2xl border border-blue-900/70' in response.text
    assert 'class="mx-auto max-w-5xl rounded-2xl' not in response.text


def test_manifesto_module_renders_guiding_principles(authenticated_client):
    response = authenticated_client.get("/manifesto")

    assert response.status_code == 200
    assert "Guiding principles" in response.text
    assert "HARQIS Work Manifesto" in response.text
    assert 'class="rounded-md px-3 py-1.5 text-xs font-medium transition' in response.text
    assert 'href="/manifesto"' not in response.text


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
    assert 'role="tablist"' in response.text
    assert 'role="tab"' in response.text
    assert 'role="tabpanel"' in response.text
    assert "initKeyboardLayout" in response.text
    assert "This browser" in response.text


def test_workflow_trigger_preserves_existing_dispatch_endpoint(
    authenticated_client, monkeypatch
):
    import modules.workflows.router as workflow_routes

    dispatched = {}
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
        lambda **kwargs: dispatched.update(kwargs) or "local-test-task-id",
    )

    response = authenticated_client.post("/tasks/example/example/trigger")

    assert response.status_code == 200
    assert "local-test-task-id" in response.text
    assert "Pending" in response.text
    assert dispatched["kwargs"] == {"sample": True}


def test_workflow_trigger_merges_manual_kwargs_over_scheduled_kwargs(
    authenticated_client, monkeypatch
):
    import modules.workflows.router as workflow_routes

    scheduled_kwargs = {"days": "last_month", "synthesize": True}
    manual_kwargs = {"days": 7}
    dispatched = {}
    monkeypatch.setattr(
        workflow_routes,
        "find_task",
        lambda workflow, task_key: {
            "task_path": "example.task",
            "queue": "hfl",
            "kwargs": scheduled_kwargs,
            "manual_kwargs": manual_kwargs,
        },
    )
    monkeypatch.setattr(
        workflow_routes.celery_client,
        "dispatch",
        lambda **kwargs: dispatched.update(kwargs) or "manual-test-task-id",
    )

    response = authenticated_client.post("/tasks/hfl/youtube/trigger")

    assert response.status_code == 200
    assert dispatched["kwargs"] == {"days": 7, "synthesize": True}
    assert scheduled_kwargs == {"days": "last_month", "synthesize": True}
    assert manual_kwargs == {"days": 7}


def test_registry_preserves_manual_kwargs_overrides(monkeypatch):
    import generate_registry

    monkeypatch.setattr(generate_registry, "_load_existing_registry", lambda: {})
    monkeypatch.setattr(
        generate_registry,
        "discover_workflows",
        lambda: [(
            "hfl",
            "workflows.hfl.tasks_config",
            {
                "run-job--ingest_youtube_activity": {
                    "task": "workflows.hfl.tasks.ingest_youtube.ingest_youtube_activity",
                    "schedule": None,
                    "kwargs": {"days": "last_month", "synthesize": True},
                    "manual_kwargs": {"days": 7},
                    "options": {"queue": "hfl"},
                }
            },
            "blue",
        )],
    )

    task = generate_registry.build_registry()["hfl"]["tasks"][0]

    assert task["kwargs"] == {"days": "last_month", "synthesize": True}
    assert task["manual_kwargs"] == {"days": 7}


def test_checked_in_youtube_registry_separates_manual_and_scheduled_windows():
    from modules.workflows.service import find_task

    task = find_task("hfl", "ingest_youtube_activity")

    assert task is not None
    assert task["kwargs"]["days"] == "last_month"
    assert task["manual_kwargs"] == {"days": 7}


def test_hfl_corpus_module_renders_an_empty_index(authenticated_client, monkeypatch):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: ())

    response = authenticated_client.get("/hfl-corpus")

    assert response.status_code == 200
    assert "Activity Corpus" in response.text
    assert "Everything everywhere, eventually indexed" in response.text
    assert "0 files" in response.text


def test_primary_navigation_pages_share_header_typography(
    authenticated_client, monkeypatch
):
    import modules.hfl_corpus.router as hfl_routes

    monkeypatch.setattr(hfl_routes.corpus_index, "documents", lambda: ())
    for route in ("/home", "/hfl-corpus", "/sharing", "/workflows", "/applications"):
        response = authenticated_client.get(route)

        assert response.status_code == 200
        assert 'class="page-header-eyebrow"' in response.text
        assert "page-header-title" in response.text
        assert 'class="page-header-description"' in response.text
        if route != "/home":
            assert response.text.count('aria-current="page"') == 2

    base_styles = authenticated_client.get("/home").text
    assert ".page-header-eyebrow {" in base_styles
    assert "color: #60a5fa;" in base_styles
    assert ".page-header-title {" in base_styles
    assert "font-size: 1.875rem;" in base_styles
