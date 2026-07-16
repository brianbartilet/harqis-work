"""Tenant SQLAlchemy models.

Three tables:

  tenants            — one row per paying customer (clerk_org_id + slug)
  tenant_secrets     — fernet-encrypted credential vault, one row per (tenant, app, key)
  tenant_usage       — Celery exec ledger; billing follow-up reads from here

Schemas are intentionally small. Schema migrations live in
`tenant/migrations/` — see 0001_create_tenant_tables.sql.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True)  # UUID4 string
    slug = Column(String(64), unique=True, nullable=False)
    clerk_org_id = Column(String(64), unique=True, nullable=True)
    plan = Column(String(32), nullable=False, default="starter")
    # Billing: hybrid model — flat base + per-exec overage. Cents to avoid float drift.
    base_cents = Column(Integer, nullable=False, default=4900)
    overage_cents_per_exec = Column(Integer, nullable=False, default=1)
    stripe_customer_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover — debug aid only
        return f"<Tenant {self.slug} ({self.id[:8]})>"


class TenantSecret(Base):
    __tablename__ = "tenant_secrets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "app_id", "key", name="uq_tenant_secret"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    app_id = Column(String(64), nullable=False)
    key = Column(String(64), nullable=False)
    # Fernet ciphertext (urlsafe base64). Plaintext NEVER stored — see tenant.secrets.
    ciphertext = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class TenantUsage(Base):
    __tablename__ = "tenant_usage"
    __table_args__ = (
        UniqueConstraint("task_id", "tenant_id", name="uq_tenant_usage_exec"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    task_id = Column(String(64), nullable=False)
    task_name = Column(String(255), nullable=False)
    queue = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False)  # success|failure|tenant_missing
    started_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    duration_ms = Column(Integer, nullable=True)
    # Stripe usage-record submission tracking. Billing follow-up flips this.
    billed_at = Column(DateTime(timezone=True), nullable=True)
