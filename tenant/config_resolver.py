"""apps_config.yaml resolution hook.

When a tenant context is bound and the requested app has a per-tenant
override in `tenant_secrets`, return that value. Otherwise fall through to
the existing ${ENV_VAR} resolution (i.e. the legacy single-tenant path).

This module is intentionally NOT wired into the apps_config loader yet —
the loader call-site (apps/config_loader.py) is touched in a follow-up PR
once we have the first paying tenant. For now it's importable and tested
in isolation; existing callers see no behaviour change.
"""

from __future__ import annotations

import os
from typing import Optional

from tenant.context import current_tenant


def resolve_app_config(app_id: str, key: str, env_var: Optional[str] = None) -> Optional[str]:
    """Prefer per-tenant secret over the legacy env-var resolution.

    Resolution order:
      1. tenant_secrets[current_tenant][app_id][key]   — if tenant is bound
      2. os.environ[env_var]                           — legacy single-tenant
      3. None
    """
    ctx = current_tenant()
    if ctx is not None:
        try:
            from tenant.secrets import load_secret, MasterKeyMissing

            try:
                value = load_secret(ctx.tenant_id, app_id, key)
                if value is not None:
                    return value
            except MasterKeyMissing:
                # Tenant context bound but secrets backend not configured.
                # Fall through to env — surface in logs at the call site.
                pass
        except ImportError:
            # cryptography / sqlalchemy not installed → legacy mode only.
            pass

    if env_var:
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return env_value

    return None
