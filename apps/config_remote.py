"""
Remote configuration backends for distributed Celery worker nodes.

The CONFIG_SOURCE env var controls where config is loaded from:
  local (default) — reads apps_config.yaml from local disk (existing behaviour)
  redis            — fetches the pre-resolved config dict from a Redis key on the host
  http             — fetches the pre-resolved config dict from the host config HTTP server

Environment variables consumed by each backend:

  Redis backend (CONFIG_SOURCE=redis):
    CONFIG_REDIS_URL   Redis URL (default: REDIS_URL env var, then redis://localhost:6379/1)
    CONFIG_REDIS_KEY   Redis key holding the JSON blob  (default: harqis:config)

  HTTP backend (CONFIG_SOURCE=http):
    CONFIG_SERVER_URL    Base URL of the config server (default: http://localhost:8765)
    CONFIG_SERVER_TOKEN  Bearer token for auth         (default: no auth)
    CONFIG_SERVER_PORT   Port the server listens on    (default: 8765)

Host-side CLI (run on the machine that has apps.env + apps_config.yaml):
  python -m apps.config_remote push-redis  [--redis-url URL] [--key KEY]
  python -m apps.config_remote serve-http  [--port PORT] [--token TOKEN] [--host HOST]
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ── Bootstrap env vars ────────────────────────────────────────────────────────

_REDIS_URL  = os.environ.get("CONFIG_REDIS_URL", os.environ.get("REDIS_URL", "redis://localhost:6379/1"))
_REDIS_KEY  = os.environ.get("CONFIG_REDIS_KEY", "harqis:config")
_HTTP_URL   = os.environ.get("CONFIG_SERVER_URL", "http://localhost:8765")
_HTTP_TOKEN = os.environ.get("CONFIG_SERVER_TOKEN", "")
_HTTP_PORT  = int(os.environ.get("CONFIG_SERVER_PORT", "8765"))


# ── Shared: load from local disk (host only) ─────────────────────────────────

def _load_local_config() -> Dict[str, Any]:
    """
    Read and resolve apps_config.yaml from the local filesystem.
    Must only be called on the host that has apps.env loaded and the YAML on disk.
    """
    from core.config.env_variables import ENV_APP_CONFIG, ENV_APP_CONFIG_FILE
    from core.config.loader import ConfigLoaderService
    svc = ConfigLoaderService(file_name=ENV_APP_CONFIG_FILE, base_path=ENV_APP_CONFIG)
    return svc.config


# ── Redis backend ─────────────────────────────────────────────────────────────

def push_config_to_redis(
    data: Dict[str, Any],
    redis_url: str = _REDIS_URL,
    key: str = _REDIS_KEY,
) -> None:
    """Serialize a fully-resolved config dict to a Redis key."""
    try:
        import redis as redis_lib
    except ImportError:
        raise ImportError("redis package required for Redis backend: pip install 'redis>=5.0.0'")

    client = redis_lib.Redis.from_url(redis_url, decode_responses=False)
    client.set(key, json.dumps(data))
    logger.info("Config pushed to Redis key '%s' at %s  (%d sections)", key, redis_url, len(data))


def fetch_config_from_redis(
    redis_url: str = _REDIS_URL,
    key: str = _REDIS_KEY,
) -> Dict[str, Any]:
    """Fetch and deserialize the resolved config dict from a Redis key."""
    try:
        import redis as redis_lib
    except ImportError:
        raise ImportError("redis package required for Redis backend: pip install 'redis>=5.0.0'")

    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    raw = client.get(key)
    if raw is None:
        raise RuntimeError(
            f"Config key '{key}' not found in Redis at {redis_url}. "
            "Run 'python -m apps.config_remote push-redis' on the host first."
        )
    data = json.loads(raw)
    logger.info("Config fetched from Redis key '%s'  (%d sections)", key, len(data))
    return data


# ── HTTP backend ──────────────────────────────────────────────────────────────

def fetch_config_from_http(
    url: str = _HTTP_URL,
    token: str = _HTTP_TOKEN,
) -> Dict[str, Any]:
    """Fetch the resolved config dict from the host config HTTP server."""
    try:
        import httpx
    except ImportError:
        raise ImportError("httpx package required for HTTP backend: pip install httpx")

    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(f"{url.rstrip('/')}/config", headers=headers)

    if resp.status_code == 401:
        raise PermissionError(
            "Config server rejected the bearer token. "
            "Ensure CONFIG_SERVER_TOKEN on the worker matches the host server."
        )
    resp.raise_for_status()

    data = resp.json()
    logger.info("Config fetched from HTTP server at %s  (%d sections)", url, len(data))
    return data


def run_config_server(
    data: Dict[str, Any],
    port: int = _HTTP_PORT,
    token: str = _HTTP_TOKEN,
    host: str = "0.0.0.0",
) -> None:
    """
    Start a FastAPI config HTTP server (blocking).

    Endpoints:
      GET /config  → full resolved config JSON  (bearer-token protected if token is set)
      GET /health  → liveness check with section list

    Call this on the HOST MACHINE only. Workers call fetch_config_from_http() to pull from it.
    """
    try:
        import uvicorn
        from fastapi import FastAPI, HTTPException, Security
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    except ImportError:
        raise ImportError("fastapi and uvicorn are required: pip install fastapi uvicorn")

    app = FastAPI(title="Harqis Config Server", docs_url=None, redoc_url=None)
    _bearer = HTTPBearer(auto_error=False)

    @app.get("/config")
    async def get_config(
        credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    ):
        if token:
            if credentials is None or credentials.credentials != token:
                raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
        return data

    @app.get("/health")
    async def health():
        return {"status": "ok", "sections": sorted(data.keys())}

    logger.info(
        "Config server starting on %s:%d  token_auth=%s  sections=%d",
        host, port, bool(token), len(data),
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Harqis remote config tools — run on the HOST machine only.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    pr = sub.add_parser("push-redis", help="Resolve local config and push JSON blob to Redis")
    pr.add_argument("--redis-url", default=_REDIS_URL, metavar="URL",
                    help="Redis connection URL")
    pr.add_argument("--key", default=_REDIS_KEY, metavar="KEY",
                    help="Redis key to write")

    ps = sub.add_parser("serve-http", help="Resolve local config and serve over HTTP")
    ps.add_argument("--port",  type=int, default=_HTTP_PORT, metavar="PORT",
                    help="Port to listen on")
    ps.add_argument("--token", default=_HTTP_TOKEN, metavar="TOKEN",
                    help="Bearer token (leave empty to disable auth)")
    ps.add_argument("--host",  default="0.0.0.0", metavar="HOST",
                    help="Bind address")

    args = parser.parse_args()

    if args.cmd == "push-redis":
        data = _load_local_config()
        push_config_to_redis(data, redis_url=args.redis_url, key=args.key)
        print(f"Pushed {len(data)} config section(s) to Redis key '{args.key}'")

    elif args.cmd == "serve-http":
        data = _load_local_config()
        print(f"Loaded {len(data)} config section(s). Starting server on port {args.port}...")
        run_config_server(data, port=args.port, token=args.token, host=args.host)

    else:
        parser.print_help()
        sys.exit(1)
