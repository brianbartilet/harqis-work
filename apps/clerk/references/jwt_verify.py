"""Verify Clerk-issued JWTs.

Clerk signs session JWTs with RS256 keys served from a per-instance JWKS
endpoint. We cache the JWKS in-process for 60 minutes (good enough for an
MVP; rotate by restarting). PyJWT does the signature math.

The function returns the decoded claims dict on success and raises
ClerkAuthError on anything that prevents trust — unknown kid, expired
token, bad signature, wrong audience.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

_JWKS_CACHE_TTL = 60 * 60  # 1h
_jwks_cache: dict[str, tuple[dict, float]] = {}  # url → (jwks, fetched_at)


class ClerkAuthError(RuntimeError):
    """Token is invalid, expired, or otherwise not trustable."""


def _derive_jwks_url() -> str:
    explicit = os.environ.get("CLERK_JWKS_URL", "").strip()
    if explicit:
        return explicit
    pub = os.environ.get("CLERK_PUBLISHABLE_KEY", "").strip()
    if not pub:
        raise ClerkAuthError(
            "Neither CLERK_JWKS_URL nor CLERK_PUBLISHABLE_KEY is set."
        )
    # Clerk publishable keys are prefixed `pk_test_` or `pk_live_` followed
    # by a base64-encoded Frontend API host. We avoid the decode here and
    # require the user to set CLERK_JWKS_URL explicitly — Clerk shows it in
    # the dashboard. Keeps the verifier dependency-light.
    raise ClerkAuthError(
        "CLERK_PUBLISHABLE_KEY is set but CLERK_JWKS_URL was not. "
        "Copy the JWKS URL from your Clerk dashboard → API Keys → Show JWKS."
    )


def _fetch_jwks(url: str) -> dict:
    import httpx

    cached = _jwks_cache.get(url)
    now = time.time()
    if cached and now - cached[1] < _JWKS_CACHE_TTL:
        return cached[0]

    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
    except Exception as exc:
        raise ClerkAuthError(f"Failed to fetch JWKS: {exc}") from exc
    jwks = resp.json()
    _jwks_cache[url] = (jwks, now)
    return jwks


def _find_signing_key(jwks: dict, kid: str):
    import jwt
    from jwt.algorithms import RSAAlgorithm

    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            return RSAAlgorithm.from_jwk(jwk)
    raise ClerkAuthError(f"No JWK matches kid={kid}")


def verify_jwt(token: str, *, audience: Optional[str] = None) -> dict[str, Any]:
    """Return decoded claims or raise ClerkAuthError."""
    import jwt

    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise ClerkAuthError(f"Token is not a JWT: {exc}") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise ClerkAuthError("Token header has no kid")

    jwks = _fetch_jwks(_derive_jwks_url())
    key = _find_signing_key(jwks, kid)

    audience = audience or os.environ.get("CLERK_AUDIENCE") or None

    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ClerkAuthError("Token expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise ClerkAuthError(f"Bad audience: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        raise ClerkAuthError(f"Invalid token: {exc}") from exc

    return claims
