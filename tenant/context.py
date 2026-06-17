"""Per-request / per-task tenant binding via ContextVar.

ContextVar is used (not threading.local) so the binding propagates correctly
across `asyncio` tasks in the FastAPI frontend. Celery worker tasks bind
synchronously at task_prerun (see tenant.metering).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    slug: str
    plan: str = "starter"


_current: ContextVar[Optional[TenantContext]] = ContextVar(
    "harqis_current_tenant", default=None
)


class TenantContextRequired(RuntimeError):
    """Raised when a tenant_safe task is invoked without a bound tenant.

    Prevents accidental cross-tenant data access — e.g. a task that reads
    a TENANT-scoped secret being fired from the legacy single-tenant beat
    schedule by mistake.
    """


def current_tenant() -> Optional[TenantContext]:
    return _current.get()


def set_current_tenant(ctx: TenantContext) -> object:
    return _current.set(ctx)


def clear_current_tenant(token: object) -> None:
    _current.reset(token)  # type: ignore[arg-type]


def require_tenant() -> TenantContext:
    ctx = current_tenant()
    if ctx is None:
        raise TenantContextRequired(
            "No tenant bound. This task was marked manifesto.tenant_safe=True "
            "but no tenant context was set at enqueue time. Either bind a "
            "tenant or remove tenant_safe from the manifesto."
        )
    return ctx
