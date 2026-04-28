"""
Centralized application configuration manager.

The CONFIG_SOURCE env var selects where config is loaded from at process startup:

  local (default) — reads apps_config.yaml + apps.env from local disk (existing behaviour)
  redis            — fetches the pre-resolved config dict from a Redis key on the host
  http             — fetches the pre-resolved config dict from the host config HTTP server

Remote sources (redis / http) let distributed worker nodes operate without
local copies of apps.env or apps_config.yaml. The host resolves all secrets
at push/serve time; workers receive the final dict over the network.

See docs/info/WORKER-CONFIG-DISTRIBUTION.md for full setup instructions.
"""

import logging
import os

from core.config.app_config_manager import AppConfigManager

logger = logging.getLogger(__name__)

CONFIG_SOURCE = os.environ.get("CONFIG_SOURCE", "local").lower()


class _DictService:
    """
    Minimal ConfigLoaderService-compatible wrapper for a pre-fetched config dict.
    Lets AppConfigManager be initialised from a remotely-supplied dict without
    touching the harqis-core loader internals.
    """

    def __init__(self, data: dict) -> None:
        self._data = data

    @property
    def config(self) -> dict:
        return self._data


def _build() -> tuple:
    if CONFIG_SOURCE == "redis":
        logger.info("apps_config: loading from Redis (CONFIG_SOURCE=redis)")
        from apps.config_remote import fetch_config_from_redis
        data = fetch_config_from_redis()
        svc = _DictService(data)

    elif CONFIG_SOURCE == "http":
        logger.info("apps_config: loading from HTTP server (CONFIG_SOURCE=http)")
        from apps.config_remote import fetch_config_from_http
        data = fetch_config_from_http()
        svc = _DictService(data)

    else:
        logger.debug("apps_config: loading from local disk (CONFIG_SOURCE=local)")
        from core.config.env_variables import ENV_APP_CONFIG, ENV_APP_CONFIG_FILE
        from core.config.loader import ConfigLoaderService
        svc = ConfigLoaderService(file_name=ENV_APP_CONFIG_FILE, base_path=ENV_APP_CONFIG)

    return svc, AppConfigManager(svc)


CONFIG_SERVICE, CONFIG_MANAGER = _build()
