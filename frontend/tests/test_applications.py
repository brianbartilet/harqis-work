from modules.applications.inventory import (
    clear_application_cache,
    discover_applications,
    get_application,
    resolve_document,
    resolve_test,
)
from modules.applications import inventory as inventory_module


def test_inventory_includes_aaa_and_excludes_template():
    applications = discover_applications()
    keys = {application.key for application in applications}

    assert "aaa" in keys
    assert ".template" not in keys
    assert "__pycache__" not in keys


def test_inventory_prioritizes_readme_and_validates_paths():
    application = get_application("aaa")

    assert application is not None
    assert application.documents[0].relative_path.lower() == "readme.md"
    assert resolve_document(application, "README.md") is not None
    assert resolve_document(application, "../apps_config.py") is None
    if application.tests:
        assert resolve_test(application, application.tests[0].relative_path)
    assert resolve_test(application, "apps/aaa/../../scripts/deploy.py") is None


def test_applications_page_and_document_render(authenticated_client):
    response = authenticated_client.get("/applications")
    document = authenticated_client.get("/applications/aaa/docs/README.md")

    assert response.status_code == 200
    assert "AAA" in response.text
    assert 'data-sortable-apps' in response.text
    assert "harqis_app_order" in response.text
    assert "Edit layout" in response.text
    assert "data-app-reorder" in response.text
    assert "initAppsKeyboardLayout" in response.text
    assert document.status_code == 200
    assert "Application documentation" in document.text


def test_unknown_application_is_404(authenticated_client):
    assert authenticated_client.get("/applications/not_real").status_code == 404


def test_safe_policy_ignores_paths_outside_discovered_tests(monkeypatch):
    valid = "apps/aaa/tests/unit_tests.py"
    monkeypatch.setattr(
        inventory_module,
        "load_safe_policy",
        lambda: {"aaa": (valid, "scripts/deploy.py")},
    )
    clear_application_cache()

    application = get_application("aaa")

    assert application.safe_paths == (valid,)
    clear_application_cache()


def test_application_inventory_uses_short_lived_cache(monkeypatch):
    clear_application_cache()
    calls = 0
    original = inventory_module._discover_applications

    def counted_discovery():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(inventory_module, "_discover_applications", counted_discovery)

    assert discover_applications()
    assert discover_applications()
    assert calls == 1
    clear_application_cache()
