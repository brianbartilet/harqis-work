import logging

from mcp.server.fastmcp import FastMCP
from apps.mcp.references.tools.oanda import register_oanda_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("harqis-mcp")

mcp = FastMCP("harqis-work")

logger.info("Registering OANDA tools")
register_oanda_tools(mcp)
logger.info("MCP server ready — %d tool(s) registered", len(mcp._tool_manager._tools))

if __name__ == "__main__":
    logger.info("Starting harqis-work MCP server (stdio transport)")
    mcp.run()
