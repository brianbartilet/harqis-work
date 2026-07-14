"""
Tests for the dict-aware behaviour of `apps.desktop.helpers.feed`.

`@feed` sits between the wrapped HUD task and `@init_meter`. When the
task returns a dict shaped like ``{"text": ..., "summary": ..., ...}`` we
need ``feed`` to:

  1. Extract just the dump *text* and write that to the per-day feed
     file (the file is human-readable, not a JSON log).
  2. Pass the original dict through unchanged so `@init_meter` can merge
     the metadata into its return value.

These are pure-function tests against `_extract_dump_text` + a small
in-memory exercise of the decorator.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.desktop.helpers.feed import _extract_dump_text


def test__extract_dump_text__plain_string():
    assert _extract_dump_text("hello world") == "hello world"


def test__extract_dump_text__dict_with_text_key():
    out = _extract_dump_text({
        "text": "rendered dump\n",
        "summary": "ignore me",
        "metrics": {"a": 1},
    })
    assert out == "rendered dump\n"


def test__extract_dump_text__feed_text_overrides_rendered_text():
    out = _extract_dump_text(
        {
            "text": "HUD text with private notification previews",
            "feed_text": "synthesis-only shared feed",
        }
    )
    assert out == "synthesis-only shared feed"


def test__extract_dump_text__dict_without_text_falls_back():
    """A dict missing `text` is JSON-stringified (legacy safe-stringify)."""
    out = _extract_dump_text({"foo": 1, "bar": 2})
    assert "foo" in out and "1" in out


def test__extract_dump_text__none_returns_empty():
    assert _extract_dump_text(None) == ""


def test__extract_dump_text__non_string_text_value():
    """Non-string `text` is itself stringified, not silently dropped."""
    out = _extract_dump_text({"text": 42, "summary": "x"})
    assert "42" in out


def test__feed_decorator_passes_dict_through(tmp_path):
    """`@feed` must return the wrapped function's *original* dict so the
    outer `@init_meter` can read `summary` / `metrics` keys.
    """
    from apps.desktop.helpers import feed as feed_module

    captured_block = {}

    def fake_prepend(*, path, block_text, encoding, lock_cfg):
        captured_block["path"] = path
        captured_block["block_text"] = block_text

    fake_config = {"feed": {"path_to_feed": str(tmp_path)}}

    with patch.object(feed_module, "CONFIG", fake_config), \
         patch.object(feed_module, "_prepend_with_lock", fake_prepend):

        @feed_module.feed(filename_prefix="test-feed")
        def my_task():
            return {
                "text": "the dump text\n",
                "summary": "queued 3",
                "metrics": {"x": 1},
            }

        result = my_task()

    assert isinstance(result, dict)
    assert result["summary"] == "queued 3"
    assert result["metrics"] == {"x": 1}
    assert result["text"] == "the dump text\n"
    assert "the dump text" in captured_block["block_text"]
    assert "summary" not in captured_block["block_text"]


def test__feed_decorator_noop_on_nonexistent_path(tmp_path):
    """A configured path that doesn't exist on this OS must be a no-op.

    Covers the cross-OS case too: DESKTOP_PATH_FEED=``G:\\My Drive\\LOGS``
    (a Windows drive path) on a POSIX worker is just a non-existent
    relative path here. The decorator must skip cleanly, pass the wrapped
    value through, and crucially NOT create a junk directory in the cwd
    (regression: Path(...).resolve()+mkdir used to do exactly that).
    """
    from apps.desktop.helpers import feed as feed_module

    calls = []

    def fake_prepend(*, path, block_text, encoding, lock_cfg):
        calls.append(path)

    fake_config = {"feed": {"path_to_feed": r"G:\My Drive\LOGS"}}
    cwd_before = set(os.listdir("."))

    with patch.object(feed_module, "CONFIG", fake_config), \
         patch.object(feed_module, "_prepend_with_lock", fake_prepend), \
         patch.dict(os.environ, {}, clear=False):
        os.environ.pop(feed_module._OS_FEED_ENV, None)

        @feed_module.feed(filename_prefix="hud-logs")
        def my_task():
            return {"text": "should not be written", "summary": "x"}

        result = my_task()

    assert result == {"text": "should not be written", "summary": "x"}
    assert calls == []
    assert not Path(r"G:\My Drive\LOGS").exists()
    assert set(os.listdir(".")) == cwd_before


def test__feed_decorator_os_specific_env_wins(tmp_path, monkeypatch):
    """The OS-specific override env var beats the OS-agnostic config.

    One shared apps.env can carry a Windows path in DESKTOP_PATH_FEED and
    a real macOS/Linux path in DESKTOP_PATH_FEED_<OS>; the running host
    must pick its own and write there.
    """
    from apps.desktop.helpers import feed as feed_module

    captured = {}

    def fake_prepend(*, path, block_text, encoding, lock_cfg):
        captured["path"] = path
        captured["block_text"] = block_text

    real_dir = tmp_path / "os-specific-feed"
    real_dir.mkdir()

    # Config points at a foreign Windows path; the OS override points at a
    # real existing dir for this platform and must win.
    fake_config = {"feed": {"path_to_feed": r"G:\My Drive\LOGS"}}
    monkeypatch.setenv(feed_module._OS_FEED_ENV, str(real_dir))

    with patch.object(feed_module, "CONFIG", fake_config), \
         patch.object(feed_module, "_prepend_with_lock", fake_prepend):

        @feed_module.feed(filename_prefix="hud-logs")
        def my_task():
            return {"text": "written via OS override", "summary": "s"}

        result = my_task()

    assert result["text"] == "written via OS override"
    assert str(real_dir) in str(captured["path"])
    assert "written via OS override" in captured["block_text"]


def test__feed_decorator_returns_original_value_when_write_fails(tmp_path):
    """Feed writing is a best-effort side effect; it must not mask task success."""
    from apps.desktop.helpers import feed as feed_module

    expected = {"text": "survived", "summary": "metadata"}

    def failing_prepend(*, path, block_text, encoding, lock_cfg):
        raise OSError(11, "Resource deadlock avoided")

    fake_config = {"feed": {"path_to_feed": str(tmp_path)}}

    with patch.object(feed_module, "CONFIG", fake_config), \
         patch.object(feed_module, "_prepend_with_lock", failing_prepend):

        @feed_module.feed(filename_prefix="test-feed")
        def my_task():
            return expected

        result = my_task()

    assert result is expected


def test__feed_decorator_passes_string_through(tmp_path):
    """Legacy: tasks returning a string keep working unchanged."""
    from apps.desktop.helpers import feed as feed_module

    def fake_prepend(*, path, block_text, encoding, lock_cfg):
        pass

    fake_config = {"feed": {"path_to_feed": str(tmp_path)}}

    with patch.object(feed_module, "CONFIG", fake_config), \
         patch.object(feed_module, "_prepend_with_lock", fake_prepend):

        @feed_module.feed(filename_prefix="test-feed")
        def my_task():
            return "plain string"

        result = my_task()

    assert result == "plain string"
