import importlib
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("harqis-mcp")

mcp = FastMCP("harqis-work")

# (label, module path, registrar function name)
APP_REGISTRARS = [
    ("Airtable",         "apps.airtable.mcp",       "register_airtable_tools"),
    ("Alpha Vantage",    "apps.alpha_vantage.mcp",  "register_alpha_vantage_tools"),
    ("Apify",            "apps.apify.mcp",          "register_apify_tools"),
    ("AppSheet",         "apps.appsheet.mcp",       "register_appsheet_tools"),
    ("OANDA",            "apps.oanda.mcp",          "register_oanda_tools"),
    ("YNAB",             "apps.ynab.mcp",           "register_ynab_tools"),
    ("Google Apps",      "apps.google_apps.mcp",    "register_google_apps_tools"),
    ("Google Drive",     "apps.google_drive.mcp",   "register_google_drive_tools"),
    ("TCG Marketplace",  "apps.tcg_mp.mcp",         "register_tcg_mp_tools"),
    ("Echo MTG",         "apps.echo_mtg.mcp",       "register_echo_mtg_tools"),
    ("Scryfall",         "apps.scryfall.mcp",       "register_scryfall_tools"),
    ("Telegram",         "apps.telegram.mcp",       "register_telegram_tools"),
    ("Trello",           "apps.trello.mcp",         "register_trello_tools"),
    ("Jira",             "apps.jira.mcp",           "register_jira_tools"),
    ("OwnTracks",        "apps.own_tracks.mcp",     "register_own_tracks_tools"),
    ("Orgo",             "apps.orgo.mcp",           "register_orgo_tools"),
    ("Discord",          "apps.discord.mcp",        "register_discord_tools"),
    ("Reddit",           "apps.reddit.mcp",         "register_reddit_tools"),
    ("LinkedIn",         "apps.linkedin.mcp",       "register_linkedin_tools"),
    ("Notion",           "apps.notion.mcp",         "register_notion_tools"),
    ("Anthropic",        "apps.antropic.mcp",       "register_anthropic_tools"),
    ("Gemini",           "apps.gemini.mcp",         "register_gemini_tools"),
    ("Grok",             "apps.grok.mcp",           "register_grok_tools"),
    ("OpenAI",           "apps.open_ai.mcp",        "register_open_ai_tools"),
    ("Perplexity",       "apps.perplexity.mcp",     "register_perplexity_tools"),
    ("GitHub",           "apps.github.mcp",         "register_github_tools"),
    ("Git",              "apps.git.mcp",            "register_git_tools"),
    ("Filesystem",       "apps.filesystem.mcp",     "register_filesystem_tools"),
    ("Browser",          "apps.browser.mcp",        "register_browser_tools"),
    ("Playwright",       "apps.playwright.mcp",     "register_playwright_tools"),
    ("SQLite-Vec",       "apps.sqlite_vec.mcp",     "register_sqlite_vec_tools"),
    ("Knowledge / RAG",  "workflows.knowledge.mcp", "register_knowledge_tools"),
]

# Lazy-import each app's mcp module so a missing config section in one app
# does not prevent the rest from loading. Skipped apps log a warning.
for label, module_path, fn_name in APP_REGISTRARS:
    try:
        mod = importlib.import_module(module_path)
        registrar = getattr(mod, fn_name)
        logger.info("Registering %s tools", label)
        registrar(mcp)
    except Exception as e:
        logger.warning("Skipping %s tools — %s: %s", label, type(e).__name__, e)

logger.info("MCP server ready — %d tool(s) registered", len(mcp._tool_manager._tools))

if __name__ == "__main__":
    logger.info("Starting harqis-work MCP server (stdio transport)")
    mcp.run()
