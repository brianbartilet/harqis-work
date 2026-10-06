"""Cryptographic tokens and owner/guest session helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import get_settings, hfl_share_session_ttl
from modules.hfl_shares.models import ShareGrant
from modules.hfl_shares.store import ShareStore


GUEST_COOKIE = "hfl_share_session"
REQUEST_COOKIE = "hfl_share_request"
_PUBLIC_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def _secret() -> str:
    settings = get_settings()
    return settings.hfl_share_secret_key.strip() or settings.secret_key


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt=salt)


def opaque_hash(value: str) -> str:
    return hmac.new(
        _secret().encode("utf-8"),
        (value or "").encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _handoff_cipher() -> Fernet:
    key = hmac.new(
        _secret().encode("utf-8"), b"hfl-share-handoff-v1", hashlib.sha256
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_share_link(link: str) -> str:
    return _handoff_cipher().encrypt(link.encode("utf-8")).decode("ascii")


def decrypt_share_link(encrypted: str) -> str:
    try:
        return _handoff_cipher().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise ValueError("The saved share link is unavailable.") from exc


def new_public_token() -> str:
    return secrets.token_urlsafe(32)


def valid_public_token(value: str) -> bool:
    return bool(_PUBLIC_TOKEN.fullmatch(value or ""))


def new_pin() -> str:
    return f"{secrets.randbelow(100_000_000):08d}"


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        (pin or "").encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
    )
    return f"{salt.hex()}:{digest.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        salt_hex, expected_hex = encoded.split(":", 1)
        actual = hashlib.scrypt(
            (pin or "").encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=2**14,
            r=8,
            p=1,
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (TypeError, ValueError):
        return False


def make_csrf_token(user: str) -> str:
    return _serializer("hfl-share-csrf").dumps({"user": user})


def verify_csrf_token(token: str, user: str) -> bool:
    try:
        payload = _serializer("hfl-share-csrf").loads(token, max_age=7200)
        return hmac.compare_digest(str(payload.get("user") or ""), user)
    except (BadSignature, SignatureExpired, TypeError):
        return False


def make_session_cookie(session_id: str, secret: str) -> str:
    return _serializer("hfl-share-guest-session").dumps(
        {"session_id": session_id, "secret": secret}
    )


def set_guest_cookie(response: Response, value: str, max_age: int) -> None:
    response.set_cookie(
        GUEST_COOKIE,
        value,
        max_age=max(1, max_age),
        httponly=True,
        secure=get_settings().behind_proxy,
        samesite="strict",
        path="/share",
    )


def clear_guest_cookie(response: Response) -> None:
    response.delete_cookie(GUEST_COOKIE, path="/share")


def current_grant(request: Request, store: ShareStore) -> ShareGrant | None:
    session = current_session(request, store)
    return session[0] if session else None


def current_session(
    request: Request, store: ShareStore
) -> tuple[ShareGrant, str] | None:
    token = request.cookies.get(GUEST_COOKIE, "")
    if not token:
        return None
    try:
        payload = _serializer("hfl-share-guest-session").loads(
            token,
            max_age=hfl_share_session_ttl(),
        )
        session_id = str(payload.get("session_id") or "")
        secret = str(payload.get("secret") or "")
    except (BadSignature, SignatureExpired, TypeError):
        return None
    grant = store.validate_session(session_id, opaque_hash(secret))
    return (grant, session_id) if grant else None


def make_request_cookie(request_id: str, secret: str) -> str:
    return _serializer("hfl-share-access-request").dumps(
        {"request_id": request_id, "secret": secret}
    )


def parse_request_cookie(request: Request) -> tuple[str, str] | None:
    token = request.cookies.get(REQUEST_COOKIE, "")
    if not token:
        return None
    try:
        payload = _serializer("hfl-share-access-request").loads(
            token, max_age=3600
        )
        return str(payload.get("request_id") or ""), str(
            payload.get("secret") or ""
        )
    except (BadSignature, SignatureExpired, TypeError):
        return None


def set_request_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        REQUEST_COOKIE,
        value,
        max_age=3600,
        httponly=True,
        secure=get_settings().behind_proxy,
        samesite="strict",
        path="/share",
    )


def qr_data_uri(url: str) -> str:
    import segno

    return segno.make(url, error="m").svg_data_uri(
        scale=5, border=2, xmldecl=False
    )


@dataclass(frozen=True)
class IssuedSession:
    cookie: str
    max_age: int


def issue_session(store: ShareStore, share_id: str) -> IssuedSession | None:
    secret = secrets.token_urlsafe(32)
    created = store.create_session(share_id, opaque_hash(secret))
    if not created:
        return None
    session_id, expires_at = created
    from datetime import datetime, timezone

    remaining = int(
        (
            datetime.fromisoformat(expires_at)
            - datetime.now(timezone.utc)
        ).total_seconds()
    )
    return IssuedSession(
        make_session_cookie(session_id, secret),
        max(1, remaining),
    )
