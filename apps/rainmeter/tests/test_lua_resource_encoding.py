import codecs
import os

from apps.rainmeter.references.helpers.config_builder import (
    _ensure_dirs_and_resources,
    _rainmeter_lua_bytes,
)


def test_rainmeter_lua_bytes_enables_unicode_script_mode():
    source = '-- punctuation: — • ·\nreturn "ok"\n'.encode("utf-8")

    deployed = _rainmeter_lua_bytes(source)

    assert deployed.startswith(codecs.BOM_UTF16_LE)
    assert deployed[2:].decode("utf-16-le") == source.decode("utf-8")


def test_ensure_resources_deploys_lua_as_utf16_le_with_bom(tmp_path):
    static_path = tmp_path / "static"
    bin_dir = static_path / "bin"
    bin_dir.mkdir(parents=True)
    source_text = '-- TextCycle — Unicode\nreturn "• item · detail"\n'
    source_path = bin_dir / "TextCycle.lua"
    source_path.write_text(source_text, encoding="utf-8")

    skin_dir = tmp_path / "skins" / "HARQIS"
    ini_dir = skin_dir / "DAILYRADAR"
    ini_dir.mkdir(parents=True)
    deployed_path = ini_dir / "TextCycle.lua"
    deployed_path.write_bytes(source_path.read_bytes())
    future = source_path.stat().st_mtime + 60
    os.utime(deployed_path, (future, future))

    _ensure_dirs_and_resources(static_path, skin_dir, ini_dir, True)

    deployed = deployed_path.read_bytes()
    assert deployed.startswith(codecs.BOM_UTF16_LE)
    assert deployed[2:].decode("utf-16-le") == source_path.read_bytes().decode("utf-8")
