import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_repo_root = Path(__file__).resolve().parent.parent
load_dotenv(_repo_root / ".env" / "apps.env")

# Ensure the production config file is used regardless of ENV setting
os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")

# Allow `python mcp/server.py` to resolve `apps.*` imports without PYTHONPATH
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from mcp.server.fastmcp import FastMCP
from harqis_tools.catalog import APP_CATALOG, register_app_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("harqis-mcp")

mcp = FastMCP("harqis-work")

# Backward-compatible tuple view for code that inspects the legacy symbol.
APP_REGISTRARS = [(spec.label, *spec.registrar.rsplit(".", 1)) for spec in APP_CATALOG]

# Per-node app surface filter.
#
# Set MCP_ENABLED_APPS to a comma-separated list of app labels (case-insensitive,
# matched against the first column of APP_REGISTRARS) to restrict which apps
# this MCP server registers. Unset/empty = register everything (default).
#
# Examples:
#   MCP_ENABLED_APPS=trello,discord
#   MCP_ENABLED_APPS="Knowledge / RAG, Filesystem"
_enabled_raw = os.environ.get("MCP_ENABLED_APPS", "").strip()
_enabled_filter: set[str] | None = None
if _enabled_raw:
    _enabled_filter = {name.strip().lower() for name in _enabled_raw.split(",") if name.strip()}

_total_apps = len(APP_CATALOG)
if _enabled_filter is not None:
    _filtered_specs = [
        spec for spec in APP_CATALOG
        if spec.label.lower() in _enabled_filter or spec.key.lower() in _enabled_filter
    ]
    logger.info(
        "MCP_ENABLED_APPS filter active: %d of %d apps will be registered (%s)",
        len(_filtered_specs), _total_apps,
        ", ".join(spec.label for spec in _filtered_specs) or "<none>",
    )
else:
    _filtered_specs = list(APP_CATALOG)

_filtered_registrars = [(spec.label, *spec.registrar.rsplit(".", 1)) for spec in _filtered_specs]

# Lazy-import each app's mcp module so a missing config section in one app
# does not prevent the rest from loading. Skipped apps log a warning.
for spec in _filtered_specs:
    try:
        logger.info("Registering %s tools", spec.label)
        register_app_tools(mcp, spec)
    except Exception as e:
        logger.warning("Skipping %s tools — %s: %s", spec.label, type(e).__name__, e)

logger.info(
    "MCP server: registered %d tool(s) from %d app(s) (filtered from %d total)",
    len(mcp._tool_manager._tools), len(_filtered_registrars), _total_apps,
)

if __name__ == "__main__":
    logger.info("Starting harqis-work MCP server (stdio transport)")
    mcp.run()
