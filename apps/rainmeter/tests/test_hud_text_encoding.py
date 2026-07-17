import codecs
import inspect
import os

from apps.rainmeter.references.helpers.config_builder import (
    _coerce_text_encoding,
    _ensure_dirs_and_resources,
    _migrate_existing_notes,
    init_meter,
)


def test_coerce_text_encoding_preserves_cp1252_punctuation():
    source = "priority — item • detail · more …"

    rendered = _coerce_text_encoding(
        source,
        encoding="cp1252",
        errors="replace",
    )

    assert rendered == source
    assert rendered.encode("cp1252").decode("cp1252") == source


def test_coerce_text_encoding_replaces_unsupported_glyphs():
    rendered = _coerce_text_encoding(
        "status ✅",
        encoding="cp1252",
        errors="replace",
    )

    assert rendered == "status ?"


def test_init_meter_defaults_all_hud_dumps_to_cp1252():
    signature = inspect.signature(init_meter)

    assert signature.parameters["notes_encoding"].default == "cp1252"
    assert signature.parameters["notes_errors"].default == "replace"


def test_migrate_existing_notes_converts_legacy_utf8(tmp_path):
    path = tmp_path / "dump.txt"
    source = "priority — item • detail · more …"
    path.write_text(source, encoding="utf-8")

    _migrate_existing_notes(path, encoding="cp1252", errors="replace")

    assert path.read_bytes().decode("cp1252") == source


def test_ensure_resources_repairs_utf16_lua_deployment(tmp_path):
    static_path = tmp_path / "static"
    bin_dir = static_path / "bin"
    bin_dir.mkdir(parents=True)
    source_text = '-- TextCycle — source\nreturn "ok"\n'
    source_path = bin_dir / "TextCycle.lua"
    source_path.write_text(source_text, encoding="utf-8")

    skin_dir = tmp_path / "skins" / "HARQIS"
    ini_dir = skin_dir / "DAILYRADAR"
    ini_dir.mkdir(parents=True)
    deployed_path = ini_dir / "TextCycle.lua"
    deployed_path.write_bytes(
        codecs.BOM_UTF16_LE + source_text.encode("utf-16-le")
    )
    future = source_path.stat().st_mtime + 60
    os.utime(deployed_path, (future, future))

    _ensure_dirs_and_resources(static_path, skin_dir, ini_dir, True)

    deployed = deployed_path.read_bytes()
    assert not deployed.startswith(codecs.BOM_UTF16_LE)
    assert deployed == source_path.read_bytes()
