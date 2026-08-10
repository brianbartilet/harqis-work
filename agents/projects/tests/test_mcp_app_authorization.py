from agents.projects.agent.tools.mcp_bridge import build_bridge
from agents.projects.agent.tools.registry import ToolRegistry
from agents.projects.permissions.enforcer import PermissionEnforcer
from agents.projects.profiles.schema import AgentProfile, ToolsConfig
from unittest.mock import MagicMock


def _profile() -> AgentProfile:
    profile = AgentProfile(id="agent:test", name="MCP app test")
    profile.tools = ToolsConfig(allowed=["read_file"], mcp_apps=["filesystem"])
    return profile


def test_selected_mcp_app_authorizes_its_tools_despite_native_allowlist():
    profile = _profile()
    enforcer = PermissionEnforcer(profile)
    bridge = build_bridge(profile.tools.mcp_apps, enforcer=enforcer)
    assert bridge is not None
    definitions = bridge.definitions_with_apps()
    assert any(app == "filesystem" and d["name"] == "fs_read_file" for app, d in definitions)
    enforcer.check_tool("fs_read_file", app_key="filesystem")


def test_registry_advertises_selected_app_tools_with_native_allowlist(sample_card):
    profile = _profile()
    registry = ToolRegistry(
        profile=profile,
        card=sample_card,
        provider=MagicMock(),
        enforcer=PermissionEnforcer(profile),
    )
    names = {definition["name"] for definition in registry.definitions()}
    assert "read_file" in names
    assert "fs_read_file" in names


def test_unselected_app_does_not_bypass_native_allowlist():
    enforcer = PermissionEnforcer(_profile())
    try:
        enforcer.check_tool("create_trello_card", app_key="trello")
    except Exception as exc:
        assert "not in the allowed list" in str(exc)
    else:
        raise AssertionError("unselected MCP app tool should be denied")


def test_bridge_catalog_includes_previously_drifted_apps():
    from agents.projects.agent.tools.mcp_bridge import _APP_LOADERS
    assert {"android_emulator", "antropic", "confluence", "sqlite_vec", "knowledge", "memory"} <= set(_APP_LOADERS)
