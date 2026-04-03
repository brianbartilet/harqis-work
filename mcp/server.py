import logging

from mcp.server.fastmcp import FastMCP
from mcp.references.tools.oanda import register_oanda_tools
from mcp.references.tools.ynab import register_ynab_tools
from mcp.references.tools.google_apps import register_google_apps_tools
from mcp.references.tools.tcg_mp import register_tcg_mp_tools
from mcp.references.tools.echo_mtg import register_echo_mtg_tools
from mcp.references.tools.scryfall import register_scryfall_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("harqis-mcp")

mcp = FastMCP("harqis-work")

logger.info("Registering OANDA tools")
register_oanda_tools(mcp)

logger.info("Registering YNAB tools")
register_ynab_tools(mcp)

logger.info("Registering Google Apps tools")
register_google_apps_tools(mcp)

logger.info("Registering TCG Marketplace tools")
register_tcg_mp_tools(mcp)

logger.info("Registering Echo MTG tools")
register_echo_mtg_tools(mcp)

logger.info("Registering Scryfall tools")
register_scryfall_tools(mcp)

logger.info("MCP server ready — %d tool(s) registered", len(mcp._tool_manager._tools))

if __name__ == "__main__":
    logger.info("Starting harqis-work MCP server (stdio transport)")
    mcp.run()
