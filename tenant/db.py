"""Lazy SQLAlchemy engine + session factory.

Engine is built on first call. If `DATABASE_URL` is unset the helpers raise
`TenantBackendDisabled` so callers can short-circuit cleanly — this is the
signal that the host is running in legacy single-tenant mode.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session


class TenantBackendDisabled(RuntimeError):
    """DATABASE_URL is not configured — multi-tenant mode is off."""


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise TenantBackendDisabled(
            "DATABASE_URL is unset — multi-tenant mode is disabled. "
            "Set it (e.g. postgresql+psycopg2://... or sqlite:///./harqis_tenant.db) "
            "to enable tenant tables."
        )
    return url


@lru_cache(maxsize=1)
def get_engine() -> "Engine":
    from sqlalchemy import create_engine

    url = _database_url()
    # SQLite needs check_same_thread=False for the FastAPI + Celery cohabitation;
    # Postgres ignores the kwarg.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


def get_session() -> "Session":
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)
    return Session()


def backend_available() -> bool:
    try:
        _database_url()
        return True
    except TenantBackendDisabled:
        return False
