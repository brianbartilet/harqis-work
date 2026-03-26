import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request

from config import get_settings

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
