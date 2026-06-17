"""CLI helper: create a tenant row.

Usage:
    python -m tenant.create_cli <slug> [--clerk-org <id>] [--plan starter|pro|scale]

Used by the operator until the self-serve signup UI lands (follow-up PR).
"""

from __future__ import annotations

import argparse
import sys
import uuid

from tenant.db import TenantBackendDisabled, get_session
from tenant.models import Tenant


_PLANS = {
    "starter": (4900, 1),  # $49 base + $0.01/exec
    "pro":     (19900, 1),  # $199 base + $0.01/exec — fewer overage execs in practice
    "scale":   (49900, 0),  # $499 flat, no overage
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a tenant")
    parser.add_argument("slug")
    parser.add_argument("--clerk-org", default=None)
    parser.add_argument("--plan", choices=list(_PLANS.keys()), default="starter")
    args = parser.parse_args(argv)

    try:
        with get_session() as session:
            tenant = Tenant(
                id=str(uuid.uuid4()),
                slug=args.slug,
                clerk_org_id=args.clerk_org,
                plan=args.plan,
                base_cents=_PLANS[args.plan][0],
                overage_cents_per_exec=_PLANS[args.plan][1],
            )
            session.add(tenant)
            session.commit()
            print(f"created tenant {tenant.id} slug={tenant.slug} plan={tenant.plan}")
            return 0
    except TenantBackendDisabled as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
