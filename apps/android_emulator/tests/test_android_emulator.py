"""Unit tests for apps/android_emulator — subprocess fully mocked.

These never launch a real emulator or require the SDK to be installed; every
test patches config/client internals so they run anywhere (CI included).
"""
import pytest

from apps.android_emulator import client, config


# ── config.merge_profile ──────────────────────────────────────────────────────

def _fake_section(monkeypatch, section: dict):
    monkeypatch.setattr(config, "_config_section", lambda: section)


def test__merge_profile_uses_default_and_overrides(monkeypatch):
    _fake_section(monkeypatch, {
        "default_profile": "p1",
        "profiles": {"p1": {"device": "pixel_7", "image": "img", "port": 5554}},
    })
    cfg = config.merge_profile(None, {"port": 5600, "headless": True})
    assert cfg["profile"] == "p1"
    assert cfg["device"] == "pixel_7"
    assert cfg["port"] == 5600          # override wins
    assert cfg["headless"] is True


def test__merge_profile_ignores_none_overrides(monkeypatch):
    _fake_section(monkeypatch, {"profiles": {"p1": {"port": 5554}}})
    cfg = config.merge_profile("p1", {"port": None, "gpu": None})
    assert cfg["port"] == 5554          # None override did not clobber


def test__merge_profile_unknown_name_raises(monkeypatch):
    _fake_section(monkeypatch, {"profiles": {"p1": {}}})
    with pytest.raises(KeyError):
        config.merge_profile("does-not-exist")


def test__tool_path_unknown_tool_raises():
    with pytest.raises(ValueError):
        config.tool_path("not-a-tool")


# ── client parsing / orchestration ────────────────────────────────────────────

def test__list_running_parses_adb_devices(monkeypatch):
    sample = "List of devices attached\nemulator-5554\tdevice\nemulator-5556\toffline\n"
    monkeypatch.setattr(client, "_run",
                        lambda *a, **k: client.CmdResult(True, 0, sample, ""))
    running = client.list_running()
    assert running == [
        {"serial": "emulator-5554", "port": 5554, "state": "device"},
        {"serial": "emulator-5556", "port": 5556, "state": "offline"},
    ]


def test__launch_derives_name_and_maps_ram_to_memory(monkeypatch):
    monkeypatch.setattr(config, "merge_profile", lambda p, o: {
        "profile": "pixel7-test", "ram_mb": 4096, "cores": 4, "port": 5554,
        "headless": True,
    })
    captured = {}

    def fake_start(name, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        return {"success": True, "serial": "emulator-5554"}

    monkeypatch.setattr(client, "start_emulator", fake_start)
    out = client.launch(profile="pixel7-test")
    assert out["success"] is True
    assert captured["name"] == "pixel7-test"        # name derived from profile
    assert captured["kwargs"]["memory_mb"] == 4096  # ram_mb → memory_mb
    assert captured["kwargs"]["cores"] == 4


def test__headless_defaults_gpu_to_swiftshader(monkeypatch):
    """Headless launches with no explicit GPU must use the software renderer."""
    captured = {}

    class _P:
        pid = 123

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return _P()

    monkeypatch.setattr(config, "tool_path", lambda name: __import__("pathlib").Path("emulator"))
    monkeypatch.setattr(config, "tool_env", lambda: {})
    monkeypatch.setattr(client.subprocess, "Popen", fake_popen)
    client.start_emulator("avd1", headless=True)  # gpu unset
    cmd = captured["cmd"]
    assert "swiftshader_indirect" in cmd
    assert "-no-window" in cmd


def test__tool_env_injects_java_home_when_resolvable(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "resolve_sdk_root", lambda: tmp_path / "sdk")
    monkeypatch.setattr(config, "resolve_java_home", lambda: tmp_path / "jdk")
    env = config.tool_env()
    assert env["JAVA_HOME"] == str(tmp_path / "jdk")
    assert env["ANDROID_SDK_ROOT"] == str(tmp_path / "sdk")
    assert str(tmp_path / "jdk" / "bin") in env["PATH"]


def test__create_from_profile_requires_image(monkeypatch):
    monkeypatch.setattr(config, "merge_profile", lambda p, o: {"profile": "x"})
    res = client.create_from_profile(profile="x")
    assert res.ok is False
    assert "image" in res.stderr


def test__run_reports_missing_sdk(monkeypatch):
    monkeypatch.setattr(config, "tool_path", lambda name: None)
    res = client._run("adb", ["devices"])
    assert res.ok is False
    assert res.returncode == 127
    assert "not found" in res.stderr


def test__cmdresult_as_dict_shape():
    d = client.CmdResult(True, 0, " out ", " err ").as_dict()
    assert d == {"success": True, "returncode": 0, "stdout": "out", "stderr": "err"}


# ── MCP module wiring ──────────────────────────────────────────────────────────

def test__mcp_registrar_registers_tools():
    """register_android_emulator_tools should add the emulator_* tools."""
    from mcp.server.fastmcp import FastMCP
    from apps.android_emulator.mcp import register_android_emulator_tools

    m = FastMCP("test")
    register_android_emulator_tools(m)
    names = set(m._tool_manager._tools)
    assert {"emulator_start", "emulator_stop", "emulator_create_avd",
            "emulator_sdk_info", "emulator_snapshot_save"} <= names


def test__adb_shell_whitelist_blocks_unlisted(monkeypatch):
    """The MCP adb-shell tool must reject non-whitelisted verbs."""
    from mcp.server.fastmcp import FastMCP
    from apps.android_emulator.mcp import register_android_emulator_tools

    m = FastMCP("test")
    register_android_emulator_tools(m)
    tool = m._tool_manager._tools["emulator_adb_shell"]
    fn = tool.fn
    # 'rm' is not whitelisted → blocked without ever calling adb.
    out = fn("emulator-5554", "rm -rf /sdcard")
    assert out["success"] is False
    assert "whitelist" in out["error"]
