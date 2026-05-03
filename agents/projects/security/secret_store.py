"""
SecretStore — scoped secret injection for agent profiles.

The orchestrator holds all secrets (from .env/apps.env).
Each agent profile declares exactly which env-var names it needs
under `secrets.required`. SecretStore extracts only those vars and
returns a scoped dict — agents never see the full environment.

Design for distributed workers
───────────────────────────────
When Celery workers are introduced, the orchestrator encrypts the
scoped secret dict with Fernet (symmetric key stored only on the
orchestrator) before encoding it into the task payload. Workers
decrypt at task-start, use the secrets, and discard them after the
agent completes. Workers never have access to the full .env file.

The `encrypt` / `decrypt` helpers are ready for that path but are
*not* required in the local single-process setup.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Names that are never injected regardless of what a profile requests
_BLOCKED_VARS: frozenset[str] = frozenset()


class SecretStore:
    """
    Extracts and scopes secrets from the host environment.

    Args:
        env: Mapping of all available secrets (defaults to os.environ).
        encryption_key: Optional 32-byte URL-safe base64 Fernet key.
                        When provided, `pack` / `unpack` encrypt the
                        payload for safe transmission to worker nodes.
    """

    def __init__(
        self,
        env: Optional[dict[str, str]] = None,
        encryption_key: Optional[bytes] = None,
    ) -> None:
        self._env: dict[str, str] = dict(env or os.environ)
        self._key: Optional[bytes] = encryption_key

    # ── Scoping ───────────────────────────────────────────────────────────────

    def scoped(self, required: list[str]) -> dict[str, str]:
        """
        Return only the secrets named in *required*.

        Raises KeyError if a required var is missing (fail-fast — don't
        let an agent run with incomplete credentials).
        """
        result: dict[str, str] = {}
        missing: list[str] = []
        for name in required:
            if name in _BLOCKED_VARS:
                logger.warning("SecretStore: blocked var requested: %s", name)
                continue
            if name not in self._env:
                missing.append(name)
            else:
                result[name] = self._env[name]
        if missing:
            raise KeyError(f"Required secrets not found in environment: {missing}")
        logger.debug("SecretStore: scoped %d secret(s) for %d requested", len(result), len(required))
        return result

    def scoped_for_profile(self, profile) -> dict[str, str]:
        """Convenience wrapper: extract secrets declared by an AgentProfile."""
        required = getattr(profile.secrets, "required", []) if hasattr(profile, "secrets") else []
        return self.scoped(required)

    # ── Serialisation for worker payloads ─────────────────────────────────────

    def pack(self, secrets: dict[str, str]) -> str:
        """
        Serialise a scoped secret dict to a string suitable for a task
        payload.  If an encryption key was provided, the output is
        encrypted; otherwise it is plain base64 JSON (dev mode only).
        """
        raw = json.dumps(secrets).encode()
        if self._key:
            return self._fernet_encrypt(raw)
        # dev/test fallback — clearly labelled
        encoded = base64.urlsafe_b64encode(raw).decode()
        return f"plain:{encoded}"

    def unpack(self, payload: str) -> dict[str, str]:
        """Reverse of `pack`."""
        if payload.startswith("plain:"):
            raw = base64.urlsafe_b64decode(payload[6:])
            return json.loads(raw)
        if self._key:
            raw = self._fernet_decrypt(payload.encode())
            return json.loads(raw)
        raise ValueError("Encrypted payload but no encryption key configured")

    # ── Fernet helpers ────────────────────────────────────────────────────────

    def _fernet_encrypt(self, data: bytes) -> str:
        try:
            from cryptography.fernet import Fernet  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "Install 'cryptography' to use encrypted secret payloads: "
                "pip install cryptography"
            ) from exc
        f = Fernet(self._key)
        return f.encrypt(data).decode()

    def _fernet_decrypt(self, token: bytes) -> bytes:
        from cryptography.fernet import Fernet  # type: ignore
        f = Fernet(self._key)
        return f.decrypt(token)

    # ── Key generation helper ─────────────────────────────────────────────────

    @staticmethod
    def generate_key() -> bytes:
        """Generate a new Fernet key. Store this on the orchestrator only."""
        try:
            from cryptography.fernet import Fernet  # type: ignore
            return Fernet.generate_key()
        except ImportError as exc:
            raise ImportError("pip install cryptography") from exc
