import logging
import os
from pathlib import Path
from dotenv import load_dotenv

_repo_root = Path(__file__).resolve().parent.parent
load_dotenv(_repo_root / ".env" / "apps.env")

from mcp.server.fastmcp import FastMCP
from apps.oanda.mcp import register_oanda_tools
from apps.ynab.mcp import register_ynab_tools
from apps.google_apps.mcp import register_google_apps_tools
from apps.tcg_mp.mcp import register_tcg_mp_tools
from apps.echo_mtg.mcp import register_echo_mtg_tools
from apps.scryfall.mcp import register_scryfall_tools
from apps.telegram.mcp import register_telegram_tools
from apps.trello.mcp import register_trello_tools
from apps.jira.mcp import register_jira_tools
from apps.own_tracks.mcp import register_own_tracks_tools

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

logger.info("Registering Telegram tools")
register_telegram_tools(mcp)

logger.info("Registering Trello tools")
register_trello_tools(mcp)

logger.info("Registering Jira tools")
register_jira_tools(mcp)

logger.info("Registering OwnTracks tools")
register_own_tracks_tools(mcp)

logger.info("MCP server ready — %d tool(s) registered", len(mcp._tool_manager._tools))

if __name__ == "__main__":
    logger.info("Starting harqis-work MCP server (stdio transport)")
    mcp.run()
