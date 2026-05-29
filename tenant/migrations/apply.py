"""Apply the one-shot tenant schema migration.

Usage:
    python -m tenant.migrations.apply             # apply 0001_create_tenant_tables
    python -m tenant.migrations.apply --downgrade # drop the tables

Why not Alembic? The repo has zero existing migrations and one table-set
to ship. Alembic adds a top-level versions/ tree, an env.py, and an
alembic.ini for a single SQL file. We use SQLAlchemy's metadata.create_all
(idempotent) plus a hand-written DROP for downgrade. When the second
migration lands we'll convert to Alembic in the same PR that introduces it.
"""

from __future__ import annotations

import argparse
import sys

from tenant.db import TenantBackendDisabled, get_engine
from tenant.models import Base


def upgrade() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    print(f"applied 0001_create_tenant_tables ({engine.url.render_as_string(hide_password=True)})")


def downgrade() -> None:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    print(f"dropped tenant tables ({engine.url.render_as_string(hide_password=True)})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tenant schema migration")
    parser.add_argument("--downgrade", action="store_true", help="Drop tenant tables")
    args = parser.parse_args(argv)
    try:
        if args.downgrade:
            downgrade()
        else:
            upgrade()
        return 0
    except TenantBackendDisabled as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
