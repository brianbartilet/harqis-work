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

    model_config = SettingsConfigDict(
        env_file=[str(_APPS_ENV), str(_LOCAL_ENV)],
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def warn_insecure_defaults(settings: Settings) -> None:
    """Log warnings if the app is still using default credentials or secret key."""
    for field, default in _INSECURE_DEFAULTS.items():
        if getattr(settings, field) == default:
            logger.warning(
                "SECURITY: %s is set to the default value — change it before "
                "exposing this app to the network. Set %s in .env/apps.env",
                field,
                field.upper(),
            )
