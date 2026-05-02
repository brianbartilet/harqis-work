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
