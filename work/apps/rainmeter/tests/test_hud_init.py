# test_config_builder.py
from pathlib import Path
import configparser
import pytest

# Import the module under test
import work.apps.rainmeter.references.helpers.config_builder as hud  # <-- adjust if needed


# ---------- helpers ----------

def make_static_tree(root: Path) -> Path:
    """
    Create minimal static layout expected by the builder:
      ROOT/Applications/Rainmeter/static/{@Resources, Options, bin/LuaTextFile.lua, base.ini}
    """
    static = root / "Applications" / "Rainmeter" / "static"
    (static / "@Resources").mkdir(parents=True, exist_ok=True)
    (static / "Options").mkdir(parents=True, exist_ok=True)
    (static / "bin").mkdir(parents=True, exist_ok=True)

    # Minimal Lua and template INI
    (static / "bin" / "LuaTextFile.lua").write_text("-- dummy lua\n", encoding="utf-8")
    (static / "base.ini").write_text(
        "[meterTitle]\n"
        "text=\n\n"
        "[MeterBackground]\n"
        "shape=Rectangle 0,0,100,100,5 | Stroke Color [#darkColor]\n",
        encoding="utf-8",
    )
    return static


def read_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(path)
    return cp


# ---------- fixtures ----------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """
    Prepare:
      - ROOT temp folder
      - static tree under ROOT/Applications/Rainmeter/static
      - write target under ROOT/Workflows/hud/skins
      - patched CONFIG and patched side effects
    """
    root = tmp_path / "ROOT"
    root.mkdir(parents=True, exist_ok=True)

    static = make_static_tree(root)
    write_root = root / "Workflows" / "hud" / "skins"
    write_root.mkdir(parents=True, exist_ok=True)

    # Patch CONFIG to include all required keys
    hud.CONFIG = {
        "skin_name": "MySkin",
        "bin_path": r"C:\Rainmeter\Rainmeter.exe",  # subprocess is stubbed
        "static_path": str(static),
        "write_skin_to_path": str(write_root),
    }

    # Stub side effects
    calls = {"subprocess": [], "beeps": []}

    def fake_run(argv, **kwargs):
        # Capture calls so we can assert behavior
        calls["subprocess"].append(list(argv))
        return 0

    def fake_beep(freq, dur):
        calls["beeps"].append((freq, dur))

    # IMPORTANT: the implementation uses subprocess.run
    monkeypatch.setattr(hud.subprocess, "run", fake_run, raising=True)
    monkeypatch.setattr(hud.winsound, "Beep", fake_beep, raising=True)

    return {"root": root, "static": static, "write_root": write_root, "calls": calls}


# ---------- tests ----------

def test_first_run_warn_then_reset(sandbox, monkeypatch):
    """
    First run with include_notes_bin=True creates a new dump.txt,
    so comparing against non-existent/old content yields updated=True
    => alertColor pre-reset, then reset back to darkColor.
    """
    root = sandbox["root"]

    # capture path to inspect during fake sleep
    pre_reset_marker = {"seen": None}

    def fake_sleep(_secs):
        # check the INI content that exists BEFORE the reset block runs
        ini_file = (
            root / "Workflows" / "hud" / "skins" / "MySkin" / "MyHUD" / "MyHUD.ini"
        )
        cp = read_ini(ini_file)
        shape = cp.get("MeterBackground", "shape")
        pre_reset_marker["seen"] = shape

    monkeypatch.setattr(hud.time, "sleep", fake_sleep, raising=True)

    @hud.init_config(
        hud.CONFIG,
        hud_item_name="My HUD",
        template_name="base.ini",
        include_notes_bin=True,
        notes_file="dump.txt",
        play_sound=False,
        reset_alerts_secs=1,
    )
    def build_notes(ini: hud.ConfigHelperRainmeter):
        return "hello world"

    build_notes()

    skin_base = root / "Workflows" / "hud" / "skins" / "MySkin"
    hud_dir = skin_base / "MyHUD"
    ini_file = hud_dir / "MyHUD.ini"
    notes_file = hud_dir / "dump.txt"

    # Structure & files
    assert (skin_base / "@Resources").is_dir()
    assert (skin_base / "Options").is_dir()
    assert (hud_dir / "LuaTextFile.lua").is_file()
    assert notes_file.is_file()
    assert ini_file.is_file()

    # Notes content saved
    assert notes_file.read_text(encoding="utf-8") == "hello world"

    # Pre-reset had alertColor (new write ⇒ updated=True)
    assert pre_reset_marker["seen"] is not None
    assert "Stroke Color [#alertColor]" in pre_reset_marker["seen"]

    # After wrapper completes, file has darkColor (reset)
    cp = read_ini(ini_file)
    assert cp.get("meterTitle", "text") == "My HUD"
    assert "Stroke Color [#darkColor]" in cp.get("MeterBackground", "shape")

    # Two activate+refresh cycles (before + after reset) = 4 calls
    assert len(sandbox["calls"]["subprocess"]) == 4
    # No beep since play_sound=False
    assert sandbox["calls"]["beeps"] == []


def test_updated_true_alert_and_beep(sandbox, monkeypatch):
    """
    Existing dump.txt with different content ⇒ updated=True ⇒ alertColor pre-reset,
    beep once (play_sound=True), then reset back to darkColor.
    """
    root = sandbox["root"]
    skin_base = root / "Workflows" / "hud" / "skins" / "MySkin"
    hud_dir = skin_base / "MyHUD"
    hud_dir.mkdir(parents=True, exist_ok=True)
    (hud_dir / "dump.txt").write_text("old", encoding="utf-8")  # force 'updated'

    pre_reset_marker = {"seen": None}

    def fake_sleep(_secs):
        ini_file = hud_dir / "MyHUD.ini"
        cp = read_ini(ini_file)
        pre_reset_marker["seen"] = cp.get("MeterBackground", "shape")

    monkeypatch.setattr(hud.time, "sleep", fake_sleep, raising=True)

    @hud.init_config(
        hud.CONFIG,
        hud_item_name="My HUD",
        template_name="base.ini",
        include_notes_bin=True,
        notes_file="dump.txt",
        play_sound=True,        # expect Beep
        reset_alerts_secs=1,
    )
    def build_notes(ini: hud.ConfigHelperRainmeter):
        return "new content"

    build_notes()

    ini_file = hud_dir / "MyHUD.ini"
    cp = read_ini(ini_file)

    # Pre-reset was alertColor
    assert "Stroke Color [#alertColor]" in pre_reset_marker["seen"]
    # After reset is darkColor
    assert "Stroke Color [#darkColor]" in cp.get("MeterBackground", "shape")

    # Beep once
    assert sandbox["calls"]["beeps"] == [(hud.BEEP_FREQUENCY, hud.BEEP_DURATION_MS)]
    # 4 subprocess calls total
    assert len(sandbox["calls"]["subprocess"]) == 4


def test_always_alert_forces_alert_without_diff(sandbox, monkeypatch):
    """
    With always_alert=True, even identical notes cause alertColor pre-reset.
    Beep is off in this case to isolate the flag's effect.
    """
    root = sandbox["root"]

    pre_reset_marker = {"seen": None}
    monkeypatch.setattr(
        hud.time, "sleep",
        lambda _secs: pre_reset_marker.__setitem__(
            "seen",
            read_ini(
                root / "Workflows" / "hud" / "skins" / "MySkin" / "HUDX" / "HUDX.ini"
            ).get("MeterBackground", "shape"),
        ),
        raising=True,
    )

    @hud.init_config(
        hud.CONFIG,
        hud_item_name="HUD X",
        template_name="base.ini",
        include_notes_bin=False,
        notes_file="dump.txt",
        play_sound=False,       # ensure no beep even though 'updated' forced
        reset_alerts_secs=1,
        always_alert=True,
    )
    def fn(ini: hud.ConfigHelperRainmeter):
        return "same content"

    fn()

    ini_file = (
        root / "Workflows" / "hud" / "skins" / "MySkin" / "HUDX" / "HUDX.ini"
    )
    cp = read_ini(ini_file)

    assert "Stroke Color [#alertColor]" in pre_reset_marker["seen"]
    assert "Stroke Color [#darkColor]" in cp.get("MeterBackground", "shape")
    assert sandbox["calls"]["beeps"] == []


def test_include_notes_bin_false_skips_lua_copy(sandbox, monkeypatch):
    """
    When include_notes_bin=False, no LuaTextFile.lua should be copied.
    """
    root = sandbox["root"]
    monkeypatch.setattr(hud.time, "sleep", lambda s: None, raising=True)

    @hud.init_config(
        hud.CONFIG,
        hud_item_name="HUD Y",
        template_name="base.ini",
        include_notes_bin=False,
        notes_file="dump.txt",
        play_sound=False,
    )
    def fn(ini: hud.ConfigHelperRainmeter):
        return "x"

    fn()

    hud_dir = root / "Workflows" / "hud" / "skins" / "MySkin" / "HUDY"
    assert not (hud_dir / "LuaTextFile.lua").exists()  # no copy when include_notes_bin=False


def test_new_sections_are_added_to_ini(sandbox, monkeypatch):
    """
    Pass new_sections_dict and ensure sections are present in saved INI.
    """
    root = sandbox["root"]
    monkeypatch.setattr(hud.time, "sleep", lambda s: None, raising=True)

    @hud.init_config(
        hud.CONFIG,
        hud_item_name="HUD Z",
        template_name="base.ini",
        include_notes_bin=False,
        notes_file="dump.txt",
        new_sections_dict={"MySection": {}, "AnotherSection": {}},
        play_sound=False,
    )
    def fn(ini: hud.ConfigHelperRainmeter):
        # Optionally initialize keys
        ini["MySection"] = {"k": "v"}
        return "notes"

    fn()

    ini_file = (
        root / "Workflows" / "hud" / "skins" / "MySkin" / "HUDZ" / "HUDZ.ini"
    )
    cp = read_ini(ini_file)
    assert cp.has_section("MySection")
    assert cp.has_section("AnotherSection")
    assert cp.get("MySection", "k") == "v"
