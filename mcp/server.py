import ctypes
import logging
import os
import sys
from contextlib import contextmanager, redirect_stdout
from io import TextIOWrapper
from pathlib import Path


@contextmanager
def _stdout_to_stderr():
    """Redirect Python and inherited fd-1 output while preserving restoration."""
    sys.stdout.flush()
    saved_stdout = os.dup(1)
    os.dup2(2, 1)
    try:
        with redirect_stdout(sys.stderr):
            yield
    finally:
        native_runtime = ctypes.CDLL("msvcrt" if os.name == "nt" else None)
        native_runtime.fflush(None)
        sys.stderr.flush()
        os.dup2(saved_stdout, 1)
        os.close(saved_stdout)

# A stdio MCP server owns stdout: every byte written there must be JSON-RPC.
# Several legacy imports configure logging to stdout or print while loading
# configuration, so keep those diagnostics away from the protocol from the
# first application import onward.  The runtime transport captures the real
# stdout before the same protection is applied to tool execution below.
with _stdout_to_stderr():
    from dotenv import load_dotenv

    _repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(_repo_root / ".env" / "apps.env")

    # Ensure the production config file is used regardless of ENV setting
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")

    # Allow `python mcp/server.py` to resolve `apps.*` imports without PYTHONPATH
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

    import anyio
    from mcp.server.fastmcp import FastMCP
    from mcp.server.stdio import stdio_server
    from tools.catalog import APP_CATALOG, register_app_tools

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
with _stdout_to_stderr():
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


if os.environ.get("MCP_STDIO_LEAK_PROBE") == "1":
    @mcp.tool(name="stdio_leak_probe")
    def stdio_leak_probe() -> str:
        """Exercise Python, native-fd, and child-process stdout isolation."""
        import subprocess

        print("python stdout probe")
        os.write(1, b"native fd stdout probe\n")
        native_runtime = ctypes.CDLL("msvcrt" if os.name == "nt" else None)
        native_runtime.printf(b"buffered native stdout probe")
        subprocess.run(
            [sys.executable, "-c", "print('child stdout probe')"],
            check=True,
        )
        return "isolated"


async def _run_stdio_safely() -> None:
    """Run MCP while reserving stdout exclusively for its JSON-RPC transport."""
    protocol_binary = os.fdopen(os.dup(1), "wb", buffering=0)
    protocol_text = TextIOWrapper(
        protocol_binary,
        encoding="utf-8",
        write_through=True,
    )
    async with anyio.wrap_file(protocol_text) as protocol_stdout:
        with _stdout_to_stderr():
            async with stdio_server(stdout=protocol_stdout) as (
                read_stream,
                write_stream,
            ):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )


if __name__ == "__main__":
    logger.info("Starting harqis-work MCP server (stdio transport)")
    anyio.run(_run_stdio_safely)
