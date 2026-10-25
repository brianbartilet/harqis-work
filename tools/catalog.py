"""Canonical registry for harqis-work application tool surfaces.

The registry contains import strings only.  Listing applications therefore has no
application/config import side effects; a registrar is imported only when its app is
selected by the CLI, standalone MCP server, or in-process Kanban bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Callable, Iterable

from mcp.server.fastmcp import FastMCP


@dataclass(frozen=True)
class AppToolSpec:
    key: str
    label: str
    registrar: str
    aliases: tuple[str, ...] = ()

    def load_registrar(self) -> Callable[[FastMCP], None]:
        module_path, function_name = self.registrar.rsplit(".", 1)
        return getattr(import_module(module_path), function_name)


APP_CATALOG: tuple[AppToolSpec, ...] = (
    AppToolSpec("airtable", "Airtable", "apps.airtable.mcp.register_airtable_tools"),
    AppToolSpec("alpha_vantage", "Alpha Vantage", "apps.alpha_vantage.mcp.register_alpha_vantage_tools"),
    AppToolSpec("android_emulator", "Android Emulator", "apps.android_emulator.mcp.register_android_emulator_tools"),
    AppToolSpec("antropic", "Anthropic", "apps.antropic.mcp.register_anthropic_tools", aliases=("anthropic",)),
    AppToolSpec("apify", "Apify", "apps.apify.mcp.register_apify_tools"),
    AppToolSpec("appsheet", "AppSheet", "apps.appsheet.mcp.register_appsheet_tools"),
    AppToolSpec("browser", "Browser", "apps.browser.mcp.register_browser_tools"),
    AppToolSpec("confluence", "Confluence", "apps.confluence.mcp.register_confluence_tools"),
    AppToolSpec("discord", "Discord", "apps.discord.mcp.register_discord_tools"),
    AppToolSpec("echo_mtg", "Echo MTG", "apps.echo_mtg.mcp.register_echo_mtg_tools"),
    AppToolSpec("filesystem", "Filesystem", "apps.filesystem.mcp.register_filesystem_tools"),
    AppToolSpec("file_index", "File Index", "apps.file_index.mcp.register_file_index_tools"),
    AppToolSpec("gemini", "Gemini", "apps.gemini.mcp.register_gemini_tools"),
    AppToolSpec("git", "Git", "apps.git.mcp.register_git_tools"),
    AppToolSpec("github", "GitHub", "apps.github.mcp.register_github_tools"),
    AppToolSpec("google_apps", "Google Apps", "apps.google_apps.mcp.register_google_apps_tools"),
    AppToolSpec("google_drive", "Google Drive", "apps.google_drive.mcp.register_google_drive_tools"),
    AppToolSpec("grok", "Grok", "apps.grok.mcp.register_grok_tools"),
    AppToolSpec("hfl_corpus", "HFL Activity Corpus", "apps.hfl_corpus.mcp.register_hfl_corpus_tools", aliases=("activity_corpus",)),
    AppToolSpec("jira", "Jira", "apps.jira.mcp.register_jira_tools"),
    AppToolSpec("justtcg", "JustTCG", "apps.justtcg.mcp.register_justtcg_tools"),
    AppToolSpec("knowledge", "Knowledge / RAG", "workflows.knowledge.mcp.register_knowledge_tools", aliases=("knowledge_rag",)),
    AppToolSpec("linkedin", "LinkedIn", "apps.linkedin.mcp.register_linkedin_tools"),
    AppToolSpec("memory", "Memory Recall", "workflows.hfl.mcp.register_memory_tools", aliases=("hfl", "memory_recall")),
    AppToolSpec("mpc", "MPC", "apps.mpc.mcp.register_mpc_tools"),
    AppToolSpec("notion", "Notion", "apps.notion.mcp.register_notion_tools"),
    AppToolSpec("oanda", "OANDA", "apps.oanda.mcp.register_oanda_tools"),
    AppToolSpec("open_ai", "OpenAI", "apps.open_ai.mcp.register_open_ai_tools", aliases=("openai",)),
    AppToolSpec("orgo", "Orgo", "apps.orgo.mcp.register_orgo_tools"),
    AppToolSpec("own_tracks", "OwnTracks", "apps.own_tracks.mcp.register_own_tracks_tools", aliases=("owntracks",)),
    AppToolSpec("perplexity", "Perplexity", "apps.perplexity.mcp.register_perplexity_tools"),
    AppToolSpec("plaud", "Plaud", "apps.plaud.mcp.register_plaud_tools"),
    AppToolSpec("playwright", "Playwright", "apps.playwright.mcp.register_playwright_tools"),
    AppToolSpec("pokemon_tcg", "Pokemon TCG", "apps.pokemon_tcg.mcp.register_pokemon_tcg_tools"),
    AppToolSpec("reddit", "Reddit", "apps.reddit.mcp.register_reddit_tools"),
    AppToolSpec("scryfall", "Scryfall", "apps.scryfall.mcp.register_scryfall_tools"),
    AppToolSpec("spotify", "Spotify", "apps.spotify.mcp.register_spotify_tools"),
    AppToolSpec("sqlite_vec", "SQLite-Vec", "apps.sqlite_vec.mcp.register_sqlite_vec_tools", aliases=("sqlite-vec",)),
    AppToolSpec("stripe", "Stripe", "apps.stripe.mcp.register_stripe_tools"),
    AppToolSpec("tcg_mp", "TCG Marketplace", "apps.tcg_mp.mcp.register_tcg_mp_tools"),
    AppToolSpec("telegram", "Telegram", "apps.telegram.mcp.register_telegram_tools"),
    AppToolSpec("trello", "Trello", "apps.trello.mcp.register_trello_tools"),
    AppToolSpec("youtube", "YouTube", "apps.youtube.mcp.register_youtube_tools"),
    AppToolSpec("ynab", "YNAB", "apps.ynab.mcp.register_ynab_tools"),
)


def _normalized(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def get_app_spec(value: str) -> AppToolSpec:
    wanted = _normalized(value)
    for spec in APP_CATALOG:
        names = (spec.key, spec.label, *spec.aliases)
        if wanted in {_normalized(name) for name in names}:
            return spec
    raise KeyError(f"Unknown app '{value}'")


def select_app_specs(values: Iterable[str] | None) -> tuple[AppToolSpec, ...]:
    if values is None:
        return APP_CATALOG
    selected: list[AppToolSpec] = []
    seen: set[str] = set()
    for value in values:
        spec = get_app_spec(value)
        if spec.key not in seen:
            selected.append(spec)
            seen.add(spec.key)
    return tuple(selected)


def register_app_tools(mcp: FastMCP, spec: AppToolSpec) -> list[str]:
    before = set(mcp._tool_manager._tools)
    spec.load_registrar()(mcp)
    return [name for name in mcp._tool_manager._tools if name not in before]


_WRITE_VERBS = frozenset({
    "add", "approve", "archive", "cancel", "categorize", "click", "clone",
    "close", "commit", "create", "delete", "edit", "execute", "fill",
    "forward", "key", "merge", "move", "post", "push", "reject", "remove",
    "reply", "run", "send", "set", "start", "stop", "submit", "type",
    "update", "upload", "write",
})

_EXPLICIT_WRITE_TOOLS = frozenset({
    "sync_hfl_github_updates",
    "complete_google_task",
    "device_connect",
    "device_mirror",
    "device_pair",
    "device_tcpip",
    "download_orgo_file",
    "download_hfl_corpus_reference",
    "download_hfl_corpus_attachment",
    "download_hfl_corpus_idea_attachment",
    "download_hfl_corpus_reference_media",
    "download_hfl_corpus_reference_thumbnail",
    "emulator_adb_shell",
    "emulator_install_apk",
    "emulator_screenshot",
    "emulator_snapshot_load",
    "emulator_snapshot_save",
    "emulator_spawn",
    "fs_copy",
    "git_checkout",
    "git_pull",
    "fork_fleet_deploy",
    "fork_fleet_sync",
    "fork_fleet_test",
    "fork_fleet_write_hfl_scan",
    "mark_echo_mtg_sold",
    "orgo_bash",
    "vote_reddit",
})


def is_write_tool(tool_name: str) -> bool:
    """Conservatively classify operations that can mutate local/remote state."""
    normalized = tool_name.lower()
    return normalized in _EXPLICIT_WRITE_TOOLS or bool(set(normalized.split("_")) & _WRITE_VERBS)
