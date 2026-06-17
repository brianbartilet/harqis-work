"""Celery signal handlers that meter task executions per tenant.

Wiring (in a Celery app bootstrap module — done in a follow-up PR for the
worker side; here we ship the helpers and the FastAPI-side enqueue binder):

    from tenant.metering import register_metering
    register_metering(celery_app)

What gets recorded:
  - task_prerun  → binds current_tenant from kwargs['_tenant_id'] (if present)
                   AND records a pending TenantUsage row keyed by (task_id, tenant_id)
  - task_postrun → updates the row with status + duration_ms
  - task_failure → marks status='failure'

The Stripe usage-record API call is STUBBED in this PR (logs the payload
that *would* be submitted). The billing follow-up swaps in the real client.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from tenant.context import TenantContext, set_current_tenant, clear_current_tenant

logger = logging.getLogger(__name__)

_TENANT_KWARG = "_tenant_id"
_SLUG_KWARG = "_tenant_slug"

# task_id → (token, start_monotonic) for matching prerun → postrun
_inflight: dict[str, tuple[object, float]] = {}


def inject_tenant_kwargs(kwargs: dict[str, Any], ctx: TenantContext) -> dict[str, Any]:
    """Adds `_tenant_id` / `_tenant_slug` to task kwargs at enqueue time.

    Mirrors the pattern used by harqis-work for opaque metadata: the Celery
    task definition does NOT need to know about these; the prerun handler
    pops them before the user-defined task sees its kwargs.
    """
    kwargs = dict(kwargs)
    kwargs[_TENANT_KWARG] = ctx.tenant_id
    kwargs[_SLUG_KWARG] = ctx.slug
    return kwargs


def register_metering(celery_app) -> None:
    """Attach prerun / postrun / failure handlers to a Celery app."""
    from celery import signals

    @signals.task_prerun.connect
    def _on_prerun(task_id=None, task=None, kwargs=None, **_):
        kwargs = kwargs or {}
        tenant_id = kwargs.pop(_TENANT_KWARG, None)
        slug = kwargs.pop(_SLUG_KWARG, None)

        tenant_safe = bool(_manifesto_tenant_safe(task))
        if tenant_id is None:
            if tenant_safe:
                from tenant.context import TenantContextRequired

                raise TenantContextRequired(
                    f"Task {task.name if task else '?'} is manifesto.tenant_safe=True "
                    "but was enqueued without a tenant context."
                )
            return  # legacy single-tenant exec — nothing to meter

        ctx = TenantContext(tenant_id=tenant_id, slug=slug or "")
        token = set_current_tenant(ctx)
        _inflight[task_id] = (token, time.monotonic())
        _insert_pending_row(task_id, ctx, task)

    @signals.task_postrun.connect
    def _on_postrun(task_id=None, task=None, state=None, **_):
        slot = _inflight.pop(task_id, None)
        if slot is None:
            return
        token, started = slot
        duration_ms = int((time.monotonic() - started) * 1000)
        _finalize_row(task_id, status=(state or "SUCCESS").lower(), duration_ms=duration_ms)
        clear_current_tenant(token)

    @signals.task_failure.connect
    def _on_failure(task_id=None, exception=None, **_):
        # task_postrun will still fire; mark failure here so the row reflects truth
        # even if postrun is somehow skipped.
        _finalize_row(task_id, status="failure", duration_ms=None)


def _manifesto_tenant_safe(task) -> bool:
    """Read manifesto.tenant_safe from the Celery beat entry if present.

    Celery's task object doesn't carry beat metadata, so we look it up
    lazily from the schedule. Returns False on any error — safe default.
    """
    if task is None:
        return False
    try:
        schedule = task.app.conf.beat_schedule or {}
    except Exception:
        return False
    for entry in schedule.values():
        if entry.get("task") == task.name:
            manifesto = entry.get("manifesto") or {}
            return bool(manifesto.get("tenant_safe", False))
    return False


def _insert_pending_row(task_id: str, ctx: TenantContext, task) -> None:
    try:
        from tenant.db import backend_available, get_session
        from tenant.models import TenantUsage
    except ImportError:
        return
    if not backend_available():
        return
    try:
        with get_session() as session:
            session.add(
                TenantUsage(
                    tenant_id=ctx.tenant_id,
                    task_id=task_id,
                    task_name=getattr(task, "name", "unknown"),
                    status="pending",
                )
            )
            session.commit()
    except Exception as exc:
        logger.warning("TenantUsage insert failed for task %s: %s", task_id, exc)


def _finalize_row(task_id: str, *, status: str, duration_ms: int | None) -> None:
    try:
        from sqlalchemy import select

        from tenant.db import backend_available, get_session
        from tenant.models import TenantUsage
    except ImportError:
        return
    if not backend_available():
        return
    try:
        with get_session() as session:
            row = session.execute(
                select(TenantUsage).where(TenantUsage.task_id == task_id)
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = status
            if duration_ms is not None:
                row.duration_ms = duration_ms
            session.commit()
            _stub_stripe_usage_record(row)
    except Exception as exc:
        logger.warning("TenantUsage finalize failed for task %s: %s", task_id, exc)


def _stub_stripe_usage_record(row) -> None:
    """Logs the Stripe usage-record API call that the billing follow-up will make.

    Hybrid billing model: $49 base + $0.01/exec overage. The follow-up PR
    will (a) call `stripe.SubscriptionItem.create_usage_record(quantity=1)`
    here and (b) set row.billed_at on success. For now we only log — gives
    us a paper trail to validate the meter before we wire money.
    """
    logger.info(
        "stripe-usage-stub tenant=%s task=%s status=%s would_record_quantity=1",
        row.tenant_id, row.task_name, row.status,
    )
