import os

# Pin CWD to this repo root before any apps.*.config module imports.
# Some app configs (apps/desktop, apps/stripe) build ConfigLoaderService without
# base_path, which falls back to os.getcwd() and walks upward. If the worker
# was launched from elsewhere (e.g. inside harqis-core, which has its own
# stale apps_config.yaml at its root), the lookup picks the wrong file.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    if os.path.isfile(os.path.join(_REPO_ROOT, "apps_config.yaml")):
        os.chdir(_REPO_ROOT)
except OSError:
    pass
