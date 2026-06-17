import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
_signer = URLSafeTimedSerializer(settings.secret_key, salt="session")


# ── Session tokens ─────────────────────────────────────────────────────────

def create_session_token(username: str) -> str:
    return _signer.dumps({"user": username})


def verify_session_token(token: str) -> Optional[str]:
    try:
        data = _signer.loads(token, max_age=settings.session_max_age)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if not token:
        return None
    return verify_session_token(token)


# ── Login rate limiter ─────────────────────────────────────────────────────
# Simple in-memory tracker: max 5 failures per IP within a 15-minute window.
# Resets automatically after the window expires or on a successful login.

_WINDOW    = timedelta(minutes=15)
_MAX_FAILS = 5

_lock:   threading.Lock                      = threading.Lock()
_failed: dict[str, list[datetime]]          = defaultdict(list)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _prune(ip: str) -> None:
    """Remove attempts outside the current window (must hold _lock)."""
    cutoff = _now() - _WINDOW
    _failed[ip] = [t for t in _failed[ip] if t > cutoff]


def is_rate_limited(ip: str) -> bool:
    with _lock:
        _prune(ip)
        return len(_failed[ip]) >= _MAX_FAILS


def record_failed_login(ip: str) -> None:
    with _lock:
        _prune(ip)
        _failed[ip].append(_now())


def clear_failed_logins(ip: str) -> None:
    with _lock:
        _failed.pop(ip, None)


# ── Clerk auth (additive — only fires when CLERK_PUBLISHABLE_KEY is set) ────
# Legacy username/password login above keeps working untouched. The Clerk
# path is opt-in: when the env var is empty, `verify_clerk_bearer` returns
# None and the existing cookie-session flow is the only auth surface.


def clerk_enabled() -> bool:
    return bool(settings.clerk_publishable_key)


def verify_clerk_bearer(request: Request) -> Optional[dict]:
    """Verify an `Authorization: Bearer <jwt>` header against Clerk.

    Returns the decoded claims dict on success, None when no header is
    present or Clerk is disabled. Raises nothing — verification errors are
    logged and treated as anonymous (the caller falls back to cookie auth).
    """
    if not clerk_enabled():
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        from apps.clerk.references.jwt_verify import verify_jwt, ClerkAuthError
    except ImportError as exc:
        logger.warning("Clerk verifier import failed: %s", exc)
        return None

    try:
        return verify_jwt(token, audience=settings.clerk_audience or None)
    except ClerkAuthError as exc:
        logger.info("Clerk JWT rejected: %s", exc)
        return None


def tenant_from_request(request: Request):
    """Resolve a TenantContext from a Clerk JWT, or None.

    Used by /api/* routes to bind a tenant for the duration of the request.
    Falls back silently when Clerk is off or the token has no org claim.
    """
    claims = verify_clerk_bearer(request)
    if not claims:
        return None
    org_id = claims.get("org_id")
    if not org_id:
        return None
    try:
        from sqlalchemy import select

        from tenant.context import TenantContext
        from tenant.db import backend_available, get_session
        from tenant.models import Tenant
    except ImportError:
        return None
    if not backend_available():
        return None
    try:
        with get_session() as session:
            tenant = session.execute(
                select(Tenant).where(Tenant.clerk_org_id == org_id)
            ).scalar_one_or_none()
            if tenant is None:
                return None
            return TenantContext(
                tenant_id=tenant.id, slug=tenant.slug, plan=tenant.plan
            )
    except Exception as exc:
        logger.warning("tenant_from_request lookup failed: %s", exc)
        return None
