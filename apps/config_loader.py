"""Per-app config lookup helper.

Each app's config.py uses this module like so:

    from apps.config_loader import app_name_for, get_ws_config

    APP_NAME = app_name_for(__file__)
    CONFIG = get_ws_config(__file__)

Routing goes through apps.apps_config.CONFIG_SERVICE so the CONFIG_SOURCE
switch (local / redis / http) applies uniformly across apps. When the
requested section is missing, a friendly KeyError is raised that names the
loaded file and lists the keys that *are* present.
"""
import os

from core.web.services.core.config.webservice import AppConfigWSClient

from apps.apps_config import CONFIG_SERVICE


def app_name_for(file_path: str) -> str:
    """Derive the YAML section key from a config.py file path."""
    return os.path.basename(os.path.dirname(os.path.abspath(file_path))).upper()


def _raise_missing(name: str) -> "KeyError":
    config = CONFIG_SERVICE.config
    loaded = getattr(
        getattr(CONFIG_SERVICE, "_config", None),
        "full_path_to_file",
        "<remote/in-memory>",
    )
    keys = ", ".join(sorted(k for k in config if isinstance(k, str)))
    raise KeyError(
        f"Section '{name}' missing from apps_config.yaml.\n"
        f"  Loaded file:    {loaded}\n"
        f"  Available keys: {keys}\n"
        f"  Fix: add a top-level '{name}:' block to {loaded} "
        f"(see apps/.template or any other app for the schema)."
    )


def get_section(file_path: str) -> dict:
    """Return the apps_config.yaml section dict for the calling app."""
    name = app_name_for(file_path)
    config = CONFIG_SERVICE.config
    if name not in config:
        _raise_missing(name)
    return config[name]


def get_ws_config(file_path: str) -> AppConfigWSClient:
    """Return AppConfigWSClient(**section) for the calling app."""
    return AppConfigWSClient(**get_section(file_path))
