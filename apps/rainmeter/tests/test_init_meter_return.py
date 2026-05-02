"""
Tests for the dict-return contract added to `@init_meter`.

`_build_return` is the pure helper that composes the dict surfaced to
Celery / the frontend. It always carries the base shape
(`hud`, `updated`, `ini_path`, `notes_path`) and merges any extra fields
the wrapped task chose to surface (`summary`, `metrics`, `links`, …).
"""

from pathlib import Path

from apps.rainmeter.references.helpers.config_builder import _build_return


def test__build_return__always_includes_base_shape():
    out = _build_return(
        hud_item_name="JIRA BOARD",
        changed=True,
        ini_path=Path("/tmp/ini.ini"),
        note_path=Path("/tmp/dump.txt"),
        extra_fields={},
    )
    assert out["hud"] == "JIRA BOARD"
    assert out["updated"] is True
    assert out["ini_path"].endswith("ini.ini")
    assert out["notes_path"].endswith("dump.txt")


def test__build_return__merges_extra_fields():
    out = _build_return(
        hud_item_name="TCG SELL CART",
        changed=False,
        ini_path=Path("/tmp/x.ini"),
        note_path=Path("/tmp/x.txt"),
        extra_fields={
            "summary": "queued 3",
            "metrics": {"checked": 12, "queued": 3},
            "links": {"sell_cart": "https://..."},
        },
    )
    assert out["summary"] == "queued 3"
    assert out["metrics"]["checked"] == 12
    assert out["links"]["sell_cart"].startswith("https://")


def test__build_return__reserved_keys_cannot_be_overwritten():
    """Tasks cannot clobber the base contract by returning the same keys."""
    out = _build_return(
        hud_item_name="BUDGET",
        changed=False,
        ini_path=Path("/tmp/a.ini"),
        note_path=Path("/tmp/a.txt"),
        extra_fields={
            "hud": "EVIL",
            "updated": True,
            "ini_path": "/evil",
            "notes_path": "/evil",
            "summary": "ok",
        },
    )
    assert out["hud"] == "BUDGET"
    assert out["updated"] is False
    assert out["ini_path"].endswith("a.ini")
    assert out["notes_path"].endswith("a.txt")
    assert out["summary"] == "ok"


def test__build_return__none_extra_fields_is_safe():
    out = _build_return(
        hud_item_name="HUD",
        changed=False,
        ini_path=Path("/tmp/i"),
        note_path=Path("/tmp/n"),
        extra_fields=None,
    )
    assert set(out.keys()) == {"hud", "updated", "ini_path", "notes_path"}


def test__build_return__paths_are_stringified():
    """`Path` objects are coerced to str so the dict round-trips through JSON."""
    out = _build_return(
        hud_item_name="HUD",
        changed=False,
        ini_path=Path("relative.ini"),
        note_path=Path("relative.txt"),
        extra_fields={},
    )
    assert isinstance(out["ini_path"], str)
    assert isinstance(out["notes_path"], str)
