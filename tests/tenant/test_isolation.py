"""Critical correctness tests for tenant isolation.

The whole AaaS pitch falls apart if tenant X can read tenant Y's secrets,
so this file is the load-bearing safety net for the foundation PR.

Tests run against an in-process SQLite so they're hermetic and don't need
Postgres. They use a generated Fernet key — the env-var is set inside
each test, not at module import.
"""

from __future__ import annotations

import os
import uuid

import pytest


@pytest.fixture(autouse=True)
def _isolated_tenant_backend(tmp_path, monkeypatch):
    """Point every tenant import at a throwaway SQLite + fresh Fernet key.

    The lru_cache on get_engine / _fernet means we have to clear them so
    each test sees its own state. We also rebuild the schema before each
    test for the same reason.
    """
    from cryptography.fernet import Fernet

    db_path = tmp_path / "tenant.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MASTER_FERNET_KEY", Fernet.generate_key().decode())

    # Reset caches that were bound to the prior env.
    from tenant import db, secrets
    db.get_engine.cache_clear()
    secrets._fernet.cache_clear()

    from tenant.migrations.apply import upgrade
    upgrade()
    yield
    # tmp_path is cleaned by pytest; cache_clear again so the next test
    # starts from scratch.
    db.get_engine.cache_clear()
    secrets._fernet.cache_clear()


def _make_tenant(slug: str) -> str:
    from tenant.db import get_session
    from tenant.models import Tenant

    tid = str(uuid.uuid4())
    with get_session() as session:
        session.add(Tenant(id=tid, slug=slug, plan="starter"))
        session.commit()
    return tid


def test_tenant_x_cannot_read_tenant_y_secret():
    """The headline guarantee: secrets are scoped to (tenant, app, key)."""
    from tenant.secrets import store_secret, load_secret

    tenant_x = _make_tenant("acme")
    tenant_y = _make_tenant("globex")

    store_secret(tenant_x, "notion", "api_key", "secret-x")
    store_secret(tenant_y, "notion", "api_key", "secret-y")

    assert load_secret(tenant_x, "notion", "api_key") == "secret-x"
    assert load_secret(tenant_y, "notion", "api_key") == "secret-y"
    # The cross-tenant lookup MUST return None — never the other tenant's value
    # and never raise. None means "no override; fall through to env".
    assert load_secret(tenant_x, "notion", "nonexistent") is None


def test_config_resolver_prefers_tenant_secret_over_env(monkeypatch):
    """When a tenant is bound, tenant_secrets[app][key] beats os.environ[var]."""
    from tenant.config_resolver import resolve_app_config
    from tenant.context import TenantContext, set_current_tenant, clear_current_tenant
    from tenant.secrets import store_secret

    tenant_id = _make_tenant("acme")
    store_secret(tenant_id, "notion", "api_key", "tenant-secret")
    monkeypatch.setenv("NOTION_API_KEY", "env-secret")

    # No tenant bound → env wins (legacy path)
    assert resolve_app_config("notion", "api_key", "NOTION_API_KEY") == "env-secret"

    # Tenant bound → tenant secret wins
    token = set_current_tenant(TenantContext(tenant_id=tenant_id, slug="acme"))
    try:
        assert resolve_app_config("notion", "api_key", "NOTION_API_KEY") == "tenant-secret"
    finally:
        clear_current_tenant(token)


def test_config_resolver_falls_back_to_env_when_tenant_has_no_override(monkeypatch):
    from tenant.config_resolver import resolve_app_config
    from tenant.context import TenantContext, set_current_tenant, clear_current_tenant

    tenant_id = _make_tenant("acme")
    monkeypatch.setenv("NOTION_API_KEY", "env-secret")

    token = set_current_tenant(TenantContext(tenant_id=tenant_id, slug="acme"))
    try:
        # Tenant has no secret for this key → env fallback fires
        assert resolve_app_config("notion", "api_key", "NOTION_API_KEY") == "env-secret"
    finally:
        clear_current_tenant(token)


def test_require_tenant_raises_when_unbound():
    from tenant.context import TenantContextRequired, require_tenant

    with pytest.raises(TenantContextRequired):
        require_tenant()


def test_require_tenant_returns_bound_context():
    from tenant.context import (
        TenantContext, require_tenant, set_current_tenant, clear_current_tenant,
    )

    token = set_current_tenant(TenantContext(tenant_id="t1", slug="acme"))
    try:
        ctx = require_tenant()
        assert ctx.tenant_id == "t1"
        assert ctx.slug == "acme"
    finally:
        clear_current_tenant(token)


def test_inject_tenant_kwargs_roundtrip():
    """`inject_tenant_kwargs` adds the metadata the worker prerun handler expects."""
    from tenant.context import TenantContext
    from tenant.metering import inject_tenant_kwargs

    ctx = TenantContext(tenant_id="abc", slug="acme", plan="pro")
    kwargs = inject_tenant_kwargs({"k": 1}, ctx)

    assert kwargs["k"] == 1
    assert kwargs["_tenant_id"] == "abc"
    assert kwargs["_tenant_slug"] == "acme"


def test_legacy_single_tenant_mode_works_without_env(monkeypatch):
    """When DATABASE_URL is unset the backend reports unavailable cleanly."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from tenant import db
    db.get_engine.cache_clear()

    assert db.backend_available() is False
    with pytest.raises(db.TenantBackendDisabled):
        db.get_engine()
