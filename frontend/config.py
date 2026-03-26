from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file, regardless of where the server is launched from
_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    app_username: str = "admin"
    app_password: str = "changeme"
    secret_key: str = "change-me-in-production"
    celery_broker: str = "amqp://guest:guest@localhost:5672/"
    flower_url: str = "http://localhost:5555"
    flower_user: str = ""
    flower_password: str = ""
    host: str = "0.0.0.0"
    port: int = 8080
    session_max_age: int = 3600 * 8

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
