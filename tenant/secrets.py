"""Fernet-symmetric encryption for tenant_secrets rows.

The master key is loaded from `MASTER_FERNET_KEY` (32-byte urlsafe-base64).
Plaintext credentials are NEVER stored — encryption happens before INSERT,
decryption happens at config-resolution time inside the worker process.

Key rotation:
  - `MASTER_FERNET_KEY` may hold `key1` or `key1,key2,...`
  - The first key is used for encryption; all keys are tried in order for
    decryption (MultiFernet semantics). Rotate by prepending a new key,
    re-encrypting rows, then dropping the old key.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


class MasterKeyMissing(RuntimeError):
    """MASTER_FERNET_KEY env var is not set."""


@lru_cache(maxsize=1)
def _fernet():
    from cryptography.fernet import Fernet, MultiFernet

    raw = os.environ.get("MASTER_FERNET_KEY", "").strip()
    if not raw:
        raise MasterKeyMissing(
            "MASTER_FERNET_KEY is unset. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        )
    keys = [Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()]
    if len(keys) == 1:
        return keys[0]
    return MultiFernet(keys)


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode("utf-8")


def store_secret(tenant_id: str, app_id: str, key: str, value: str) -> None:
    """Encrypt and upsert a single (tenant, app, key) secret."""
    from sqlalchemy import select

    from tenant.db import get_session
    from tenant.models import TenantSecret

    ciphertext = encrypt(value)
    with get_session() as session:
        existing = session.execute(
            select(TenantSecret).where(
                TenantSecret.tenant_id == tenant_id,
                TenantSecret.app_id == app_id,
                TenantSecret.key == key,
            )
        ).scalar_one_or_none()
        if existing:
            existing.ciphertext = ciphertext
        else:
            session.add(
                TenantSecret(
                    tenant_id=tenant_id,
                    app_id=app_id,
                    key=key,
                    ciphertext=ciphertext,
                )
            )
        session.commit()


def load_secret(tenant_id: str, app_id: str, key: str) -> Optional[str]:
    """Return decrypted secret or None if not set for this tenant/app/key."""
    from sqlalchemy import select

    from tenant.db import get_session
    from tenant.models import TenantSecret

    with get_session() as session:
        row = session.execute(
            select(TenantSecret).where(
                TenantSecret.tenant_id == tenant_id,
                TenantSecret.app_id == app_id,
                TenantSecret.key == key,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return decrypt(row.ciphertext)
