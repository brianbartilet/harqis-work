# test_hud_initialize.py
import os
from pathlib import Path
import configparser
import pytest

# Import the module under test
import work.apps.rainmeter.references.helpers.config_builder as hud  # <-- change to your real module path

# --- helpers -------------------------------------------------

def make_static_tree(root: Path):
    """
    Create the minimal static layout used by initialize_hud_configuration:
    - Applications/Rainmeter/static/@Resources
    - Applications/Rainmeter/static/Options
    - Applications/Rainmeter/static/bin/LuaTextFile.lua
    - Applications/Rainmeter/static/base.ini
    """
    static = root / "Applications" / "Rainmeter" / "static"
    (static / "@Resources").mkdir(parents=True, exist_ok=True)
    (static / "Options").mkdir(parents=True, exist_ok=True)
    (static / "bin").mkdir(parents=True, exist_ok=True)

    # tiny lua file
    (static / "bin" / "LuaTextFile.lua").write_text("-- dummy lua\n", encoding="utf-8")

    # minimal template ini (must contain meterTitle.text and MeterBackground.shape with #darkColor)
    tmpl = (static / "base.ini")
    tmpl.write_text(
        "[meterTitle]\n"
        "text=\n\n"
        "[MeterBackground]\n"
        "shape=Rectangle 0,0,100,100,5 | Stroke Color [#darkColor]\n",
        encoding="utf-8",
    )
    return static


def read_ini(path: Path):
    cp = configparser.ConfigParser()
    cp.read(path)
    return cp

# --- fixtures ------------------------------------------------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """
    Prepare a fake root directory (ENV_ROOT_DIRECTORY), static layout, and a fake CONFIG.
    """
    root = tmp_path / "ROOT"
    root.mkdir(parents=True, exist_ok=True)
    static = make_static_tree(root)

    # Patch module globals (import-time imports already happened)
    monkeypatch.setattr(hud, "ENV_ROOT_DIRECTORY", str(root), raising=True)
    hud.CONFIG = {
        "skin_name": "MySkin",
        "bin_path": r"C:\Rainmeter\Rainmeter.exe",  # not executed; subprocess is stubbed
    }

    # Stub out blocking/side-effectful calls
    calls = {"subprocess": [], "beeps": []}

    def fake_call(argv):
        # store argv list for inspection
        calls["subprocess"].append(list(argv))
        return 0

    def fake_beep(freq, dur):
        calls["beeps"].append((freq, dur))

    monkeypatch.setattr(hud.subprocess, "call", fake_call, raising=True)
    monkeypatch.setattr(hud.winsound, "Beep", fake_beep, raising=True)
    monkeypatch.setattr(hud.time, "sleep", lambda s: None, raising=True)

    return {
        "root": root,
        "static": static,
        "calls": calls,
    }

# --- tests ---------------------------------------------------

def test_first_run_creates_skin_and_ini_and_resets_border(sandbox):
    """
    On first run, skin directory doesn't exist; it should copy @Resources/Options,
    create HUD folder, write LuaTextFile.lua and notes, write INI, activate/refresh,
    then reset border back to #darkColor.
    """
    root = sandbox["root"]

    # Build a decorated function that returns note content
    @hud.initialize_hud_configuration(
        hud_item_name="My HUD",
        template_name="base.ini",
        include_notes_bin=True,
        notes_file="dump.txt",
        play_sound=False,        # no beep on first run
        reset_alerts_secs=1,     # sleep is mocked anyway
    )
    def produce_notes(ini: hud.ConfigHelperRainmeter):
        # Can also mutate ini here if desired
        return "hello world"

    # Run
    produce_notes()

    skin_base = root / "Workflows" / "hud" / "skins" / "MySkin"
    hud_dir = skin_base / "MyHUD"
    ini_file = hud_dir / "MyHUD.ini"
    notes_file = hud_dir / "dump.txt"

    # Files and dirs created
    assert (skin_base / "@Resources").is_dir()
    assert (skin_base / "Options").is_dir()
    assert (hud_dir / "LuaTextFile.lua").is_file()
    assert notes_file.is_file()
    assert ini_file.is_file()

    # Notes content saved
    assert notes_file.read_text(encoding="utf-8") == "hello world"

    # INI content after reset: meterTitle.text set and border back to darkColor
    cp = read_ini(ini_file)
    assert cp.get("meterTitle", "text") == "My HUD"
    shape = cp.get("MeterBackground", "shape")
    assert "Stroke Color [#darkColor]" in shape  # reset happened

    # Two activate+refresh cycles (before and after reset)
    # i.e., 4 subprocess calls total
    assert len(sandbox["calls"]["subprocess"]) == 4

    # First activate contains correct arguments
    first = sandbox["calls"]["subprocess"][0]
    # The command is split (shlex); check tokens rather than an exact string
    assert "C:\\Rainmeter\\Rainmeter.exe" in first[0]
    assert "!ActivateConfig" in first
    assert "MySkin\\MyHUD" in " ".join(first)
    assert "MyHUD.ini" in " ".join(first)


def test_updated_path_triggers_alert_color_and_beep_when_enabled(sandbox, monkeypatch):
    """
    Simulate an existing different notes file to make 'updated' True.
    Verify alert border, beep, and same reset back to darkColor.
    """
    root = sandbox["root"]

    # Pre-create skin structure so copytree branch is skipped (not required, but realistic)
    skin_base = root / "Workflows" / "hud" / "skins" / "MySkin"
    hud_dir = skin_base / "MyHUD"
    (skin_base).mkdir(parents=True, exist_ok=True)
    (hud_dir).mkdir(parents=True, exist_ok=True)

    # Put an old note so filecmp.cmp will succeed and show difference
    old_notes = hud_dir / "dump.txt"
    old_notes.write_text("old", encoding="utf-8")

    # Also ensure the Lua file exists (include_notes_bin still copies if missing)
    # (Not strictly necessary: the code checks and copies when missing)
    (hud_dir / "LuaTextFile.lua").write_text("-- ok", encoding="utf-8")

    @hud.initialize_hud_configuration(
        hud_item_name="My HUD",
        template_name="base.ini",
        include_notes_bin=True,
        notes_file="dump.txt",
        play_sound=True,         # we want to observe Beep
        reset_alerts_secs=1,
    )
    def produce_new_notes(ini: hud.ConfigHelperRainmeter):
        return "new content"     # different content ⇒ updated=True

    produce_new_notes()

    ini_file = hud_dir / "MyHUD.ini"
    cp = read_ini(ini_file)

    # Border after reset is darkColor in the saved file
    shape = cp.get("MeterBackground", "shape")
    assert "Stroke Color [#darkColor]" in shape

    # Beep called once (updated=True path)
    assert sandbox["calls"]["beeps"] == [(hud.frequency, hud.duration)]

    # Subprocess calls still made for activate+refresh cycles
    assert len(sandbox["calls"]["subprocess"]) == 4


def test_always_alert_forces_updated_true_without_filecmp(sandbox):
    """
    With always_alert=True, we should get alert path regardless of filecmp result.
    (Beep disabled here to avoid asserting beeps again.)
    """
    root = sandbox["root"]

    @hud.initialize_hud_configuration(
        hud_item_name="HUD X",
        template_name="base.ini",
        include_notes_bin=False,
        notes_file="dump.txt",
        play_sound=False,
        reset_alerts_secs=1,
        always_alert=True,       # force updated
    )
    def fn(ini: hud.ConfigHelperRainmeter):
        return "something"

    fn()

    # Saved INI path
    ini_file = (
        root / "Workflows" / "hud" / "skins" / "MySkin" / "HUDX" / "HUDX.ini"
    )
    assert ini_file.is_file()

    # After reset, stored file should be back to darkColor
    cp = read_ini(ini_file)
    shape = cp.get("MeterBackground", "shape")
    assert "Stroke Color [#darkColor]" in shape


def test_helpers_write_and_save(tmp_path):
    """
    Unit test the small helpers directly, independent of the decorator.
    """
    # ConfigHelperRainmeter: save_to_new_file and read
    f = tmp_path / "x.ini"
    cfg = hud.ConfigHelperRainmeter()
    cfg["a"] = {"k": "v"}
    cfg.save_to_new_file(str(f))
    assert f.read_text() != ""  # file exists with content

    cfg2 = hud.ConfigHelperRainmeter()
    cfg2.read(str(f))
    assert cfg2.get("a", "k") == "v"

    # NotesTextHelperRainmeter
    t = tmp_path / "n.txt"
    note = hud.NotesTextHelperRainmeter(str(t))
    note.write("hello")
    assert t.read_text() == "hello"
