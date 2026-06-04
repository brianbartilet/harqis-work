"""Multi-tenant primitives for harqis-work AaaS mode.

This package is OPT-IN. When `DATABASE_URL` and `MASTER_FERNET_KEY` are
both unset, importing tenant submodules is harmless — the existing
single-tenant deployment runs unchanged.

Public surface:

  - `current_tenant()` / `set_current_tenant()`  — ContextVar binding
  - `TenantContextRequired`                      — raised by tenant_safe tasks
  - `resolve_app_config(app_id, key)`            — apps_config.yaml override hook
  - `register_metering(celery_app)`              — wires Celery signals → TenantUsage
  - `Tenant`, `TenantSecret`, `TenantUsage`      — SQLAlchemy models

The fork-per-client deployment path (the existing default) does not import
anything from this package, so unsetting the env vars is the kill-switch.
"""

from tenant.context import (  # noqa: F401
    TenantContext,
    TenantContextRequired,
    current_tenant,
    set_current_tenant,
    clear_current_tenant,
)

__all__ = [
    "TenantContext",
    "TenantContextRequired",
    "current_tenant",
    "set_current_tenant",
    "clear_current_tenant",
]
