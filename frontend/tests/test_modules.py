import re

import pytest

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


def test_framework_schema_and_interactive_docs_are_not_public(authenticated_client):
    for route in ("/openapi.json", "/docs", "/redoc"):
        response = authenticated_client.get(route)
        assert response.status_code == 404


@pytest.mark.parametrize(
    "headers",
    (
        [],
        [(b"content-length", b"1")],
    ),
)
def test_public_share_body_limit_counts_actual_streamed_bytes(headers):
    import asyncio

    from main import PUBLIC_SHARE_MAX_BODY_BYTES, PublicShareBodyLimitMiddleware

    messages = [
        {
            "type": "http.request",
            "body": b"x" * PUBLIC_SHARE_MAX_BODY_BYTES,
            "more_body": True,
        },
        {"type": "http.request", "body": b"x", "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def consume_body(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break

    middleware = PublicShareBodyLimitMiddleware(consume_body)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": headers,
    }
    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_public_share_body_limit_rejects_stream_before_unread_route_runs():
    import asyncio

    from main import PUBLIC_SHARE_MAX_BODY_BYTES, PublicShareBodyLimitMiddleware

    messages = [
        {
            "type": "http.request",
            "body": b"x" * PUBLIC_SHARE_MAX_BODY_BYTES,
            "more_body": True,
        },
        {"type": "http.request", "body": b"x", "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def unread_route(scope, receive, send):
        raise AssertionError("Oversized bodies must fail before route work.")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/logout",
        "headers": [],
    }
    middleware = PublicShareBodyLimitMiddleware(unread_route)

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


@pytest.mark.parametrize(
    "headers",
    (
        [(b"content-length", b"10"), (b"content-length", b"10")],
        [(b"content-length", b"10"), (b"content-length", b"11")],
        [(b"content-length", b"+10")],
        [(b"content-length", b"1_0")],
        [(b"content-length", b" 10")],
        [(b"content-length", b"10 ")],
        [(b"content-length", b"0x10")],
        [(b"content-length", b"-1")],
        [(b"content-length", b"")],
    ),
)
def test_public_share_body_limit_rejects_ambiguous_content_length(headers):
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Ambiguous Content-Length must fail before routing.")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": headers,
    }
    middleware = PublicShareBodyLimitMiddleware(route_must_not_run)

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 400


@pytest.mark.parametrize(
    ("headers", "messages", "expected_status"),
    (
        (
            [(b"content-length", b"0")],
            [{"type": "http.request", "body": b"x", "more_body": False}],
            400,
        ),
        (
            [(b"content-length", b"2")],
            [{"type": "http.request", "body": b"x", "more_body": False}],
            400,
        ),
        (
            [
                (b"content-length", b"1"),
                (b"transfer-encoding", b"chunked"),
            ],
            [{"type": "http.request", "body": b"x", "more_body": False}],
            400,
        ),
    ),
)
def test_public_share_body_limit_rejects_ambiguous_framing(
    headers, messages, expected_status
):
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Ambiguous framing must fail before routing.")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": headers,
    }
    middleware = PublicShareBodyLimitMiddleware(route_must_not_run)

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == expected_status


def test_public_share_body_limit_bounds_empty_stream_messages():
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    messages = [
        {"type": "http.request", "body": b"", "more_body": True},
        {"type": "http.request", "body": b"", "more_body": True},
        {"type": "http.request", "body": b"", "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Excessive body messages must fail before routing.")

    middleware = PublicShareBodyLimitMiddleware(
        route_must_not_run,
        max_body_messages=2,
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": [],
    }

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 400


def test_public_share_body_limit_enforces_receive_deadline():
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Timed-out bodies must fail before routing.")

    middleware = PublicShareBodyLimitMiddleware(
        route_must_not_run,
        body_timeout_seconds=0.01,
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": [],
    }

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 408


def test_public_share_body_limit_never_times_out_during_rejection_send():
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []
    messages = [
        {"type": "http.request", "body": b"xx", "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)
        if len(sent) == 1:
            await asyncio.sleep(0.02)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Oversized bodies must fail before routing.")

    middleware = PublicShareBodyLimitMiddleware(
        route_must_not_run,
        max_body_bytes=1,
        body_timeout_seconds=0.01,
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": [],
    }

    asyncio.run(middleware(scope, receive, send))

    response_starts = [
        message for message in sent if message["type"] == "http.response.start"
    ]
    assert [message["status"] for message in response_starts] == [413]


@pytest.mark.parametrize(
    "invalid_message",
    (
        None,
        {"type": "http.request", "body": None, "more_body": False},
        {"type": "http.request", "body": "x", "more_body": False},
        {"type": "http.request", "body": [], "more_body": False},
        {"type": "http.request", "body": b"", "more_body": 1},
        {"type": "unexpected", "body": b"", "more_body": False},
    ),
)
def test_public_share_body_limit_rejects_malformed_asgi_events(invalid_message):
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []

    async def receive():
        return invalid_message

    async def send(message):
        sent.append(message)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Malformed ASGI events must fail before routing.")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": [],
    }
    asyncio.run(PublicShareBodyLimitMiddleware(route_must_not_run)(scope, receive, send))

    assert sent[0]["status"] == 400


@pytest.mark.parametrize(
    "transfer_headers",
    (
        [(b"transfer-encoding", b"")],
        [(b"transfer-encoding", b"gzip")],
        [(b"transfer-encoding", b"chunked"), (b"transfer-encoding", b"chunked")],
    ),
)
def test_public_share_body_limit_rejects_ambiguous_transfer_encoding(
    transfer_headers,
):
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []

    async def receive():
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message):
        sent.append(message)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Ambiguous transfer framing must fail before routing.")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": transfer_headers,
    }
    asyncio.run(PublicShareBodyLimitMiddleware(route_must_not_run)(scope, receive, send))

    assert sent[0]["status"] == 400


def test_public_share_body_limit_accepts_single_chunked_transfer_encoding():
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []
    received = []

    async def receive():
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message):
        sent.append(message)

    async def consuming_route(scope, receive, send):
        received.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": [(b"transfer-encoding", b"chunked")],
    }
    asyncio.run(PublicShareBodyLimitMiddleware(consuming_route)(scope, receive, send))

    assert sent[0]["status"] == 204
    assert received[0]["body"] == b"x"


@pytest.mark.parametrize(
    "invalid_headers",
    (
        None,
        1,
        [(b"content-length",)],
        [(b"content-length", b"1", b"extra")],
        [("content-length", b"1")],
        [(b"content-length", "1")],
    ),
)
def test_public_share_body_limit_rejects_malformed_scope_headers(invalid_headers):
    import asyncio

    from main import PublicShareBodyLimitMiddleware

    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def route_must_not_run(scope, receive, send):
        raise AssertionError("Malformed scope headers must fail before routing.")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/share/session/chat",
        "headers": invalid_headers,
    }
    asyncio.run(PublicShareBodyLimitMiddleware(route_must_not_run)(scope, receive, send))

    assert sent[0]["status"] == 400


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
    assert response.text.count('role="tabpanel"') == 1
    assert 'hx-select="#workflow-panel-host"' in response.text
    assert 'hx-push-url="true"' in response.text
    assert "initKeyboardLayout" in response.text
    assert "This browser" in response.text


def test_workflow_panels_are_loaded_one_at_a_time(authenticated_client):
    from modules.workflows.service import refresh_registry

    workflows = refresh_registry()
    selected = next(key for key in workflows if key != "hud")
    response = authenticated_client.get(f"/workflows?workflow={selected}")

    assert response.status_code == 200
    assert f'id="workflow-panel-{selected}"' in response.text
    assert response.text.count('role="tabpanel"') == 1
    assert response.text.count('class="group flex flex-col') == len(
        workflows[selected]["tasks"]
    )
    assert len(response.content) < 300_000


def test_workflow_registry_skips_unchanged_source_regeneration(monkeypatch):
    import modules.workflows.service as workflow_service

    workflow_service.refresh_registry()
    monkeypatch.setattr(
        workflow_service.generate_registry,
        "main",
        lambda: (_ for _ in ()).throw(
            AssertionError("unchanged sources must not regenerate the registry")
        ),
    )

    assert workflow_service.refresh_registry()


def test_dynamic_pages_are_compressed_and_timed(authenticated_client):
    response = authenticated_client.get(
        "/workflows",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["server-timing"].startswith("app;dur=")


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
