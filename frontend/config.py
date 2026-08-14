import logging
from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).parent.parent
# Primary source: shared apps.env; frontend/.env can override locally
_APPS_ENV  = _REPO_ROOT / ".env" / "apps.env"
_LOCAL_ENV = Path(__file__).parent / ".env"

logger = logging.getLogger(__name__)

_INSECURE_DEFAULTS = {
    "app_password": "changeme",
    "secret_key":   "change-me-in-production",
}


class InsecureDefaultError(RuntimeError):
    """Raised at startup when a critical secret is left at its default value."""


class Settings(BaseSettings):
    # APP_USERNAME / APP_PASSWORD in apps.env (field name uppercased = env var name)
    app_username: str  = "admin"
    app_password: str  = "changeme"
    # APP_SECRET_KEY in apps.env
    secret_key:   str  = Field("change-me-in-production", alias="APP_SECRET_KEY")
    celery_broker: str = "amqp://guest:guest@localhost:5672/"
    flower_url:    str = "http://localhost:5555"
    flower_user:   str = ""
    flower_password: str = ""
    host:          str = "0.0.0.0"
    port:          int = 8080
    session_max_age: int = 3600 * 8
    # Set to True when the app is behind a reverse proxy / Cloudflare Tunnel.
    # Enables the Secure flag on session cookies (requires HTTPS end-to-end).
    behind_proxy:  bool = False
    # Additional local roots from which authenticated HFL reference downloads
    # are allowed. Uses the host OS path separator (`;` on Windows, `:` on Unix).
    hfl_reference_allowed_roots: str = ""
    hfl_corpus_path: str = ""
    # When set, the UI reads the canonical Mac corpus API instead of local
    # disk. The token is shared with that API and must remain in apps.env.
    hfl_corpus_api_url: str = ""
    hfl_corpus_api_token: str = ""
    # Owner-created, expiring Activity Corpus share portal.
    hfl_share_public_url: str = ""
    hfl_share_secret_key: str = ""
    hfl_share_store_path: str = str(
        _REPO_ROOT / ".harqis-data" / "hfl-shares.sqlite3"
    )
    hfl_share_default_ttl_seconds: int = 3600
    hfl_share_default_device_limit: int = 1
    hfl_share_session_ttl_seconds: int = 21_600
    hfl_share_max_concurrent_sessions: int = 20
    hfl_share_capacity_retry_seconds: int = 300
    hfl_share_pin_max_attempts: int = 5
    hfl_share_pin_attempt_window_seconds: int = 900
    hfl_share_max_guest_request_bytes: int = 16_384
    hfl_share_max_question_chars: int = 2_000
    hfl_share_live_refresh_seconds: int = 300
    hfl_share_provider: str = "hermes"
    hfl_share_hermes_base_url: str = "http://127.0.0.1:8643/v1"
    hfl_share_hermes_api_key: str = ""
    hfl_share_hermes_model: str = "share-corpus"
    hfl_share_agent_timeout_seconds: float = 90.0
    hfl_share_max_output_tokens: int = 1200
    hfl_share_max_context_chars: int = 120_000
    hfl_share_max_snapshot_chars: int = 10_000_000
    hfl_share_chat_limit_per_hour: int = 30
    hfl_share_embedding_model: str = "BAAI/bge-small-en-v1.5"
    hfl_share_embedding_cache_dir: str = str(
        _REPO_ROOT / ".harqis-data" / "models" / "fastembed"
    )
    hfl_share_retrieval_k: int = 8
    hfl_share_semantic_weight: float = 0.75
    # Trust Cloudflare Access identity headers only when the origin is locked
    # down so clients cannot reach it without the authenticated proxy.
    hfl_share_trust_proxy_identity: bool = False
    profile_store_path: str = str(
        _REPO_ROOT / ".harqis-data" / "profile.sqlite3"
    )

    model_config = SettingsConfigDict(
        env_file=[str(_APPS_ENV), str(_LOCAL_ENV)],
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def hfl_share_session_ttl(settings: Settings | None = None) -> int:
    """Return the configured guest-session lifetime within its safety bounds."""
    configured = (settings or get_settings()).hfl_share_session_ttl_seconds
    return max(300, min(86_400, int(configured)))


def hfl_share_concurrent_session_cap(settings: Settings | None = None) -> int:
    """Return the owner-selectable session cap within the hard limit."""
    configured = (settings or get_settings()).hfl_share_max_concurrent_sessions
    return max(1, min(20, int(configured)))


def hfl_share_capacity_retry(settings: Settings | None = None) -> int:
    """Return the public capacity response retry delay in seconds."""
    configured = (settings or get_settings()).hfl_share_capacity_retry_seconds
    return max(30, min(3_600, int(configured)))


def hfl_share_question_limit(settings: Settings | None = None) -> int:
    """Return the public question limit within a bounded parsing budget."""
    configured = (settings or get_settings()).hfl_share_max_question_chars
    return max(100, min(10_000, int(configured)))


def warn_insecure_defaults(settings: Settings) -> None:
    """Refuse to start when a critical secret is at its default value.

    Previously this only logged a warning; the audit (data/SECURITY_AUDIT.md,
    finding H1) flagged that as insufficient — a host running with
    `admin/changeme` is openly exploitable from anywhere it's reachable.
    Both `app_password` and `secret_key` are now hard requirements.
    """
    breached = [
        field for field, default in _INSECURE_DEFAULTS.items()
        if getattr(settings, field) == default
    ]
    if breached:
        env_vars = ", ".join(f.upper() for f in breached)
        raise InsecureDefaultError(
            "Refusing to start the dashboard: the following critical secrets "
            "are still at their default values — set them in .env/apps.env "
            f"before starting: {env_vars}"
        )
