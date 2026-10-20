"""Offline contract tests; no corpus, broker, model, or upstream MCP calls."""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.hfl.tasks import ingest_nothing_essential_space as mod

DAY = date(2026, 10, 20)


def export(root, name="meeting", text="# Planning\nLaunch waits for import fixes.",
           **metadata):
    path = root / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    path.with_suffix(".metadata.json").write_text(
        json.dumps({"captured_at": "2026-10-20T09:30:00+08:00", **metadata}),
        encoding="utf-8")
    return path


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    root = tmp_path / "inbox"
    root.mkdir()
    monkeypatch.setenv("NOTHING_ESSENTIAL_SPACE_EXPORT_DIR", str(root))
    monkeypatch.setenv("NOTHING_ESSENTIAL_SPACE_BACKEND", "export")
    monkeypatch.setattr(mod, "outbox_dir", lambda: tmp_path / "runtime" / "hfl-outbox")
    monkeypatch.setattr(mod, "BaseApiServiceAnthropic", Mock(
        side_effect=AssertionError("unexpected model call")))
    monkeypatch.setattr(mod, "submit_hfl_entry", Mock(
        side_effect=AssertionError("unexpected persistence call")))
    return root


def collect(**kwargs):
    return mod.collect_nothing_essential_space_activity(since=DAY, until=DAY, **kwargs)


def run(**kwargs):
    return mod._ingest(since=DAY.isoformat(), until=DAY.isoformat(), **kwargs)


def test_missing_config_and_empty_inbox_are_noops(inbox, monkeypatch):
    assert run()["entries_submitted"] == 0
    monkeypatch.delenv("NOTHING_ESSENTIAL_SPACE_EXPORT_DIR")
    assert run()["skipped"] == "no export inbox"
    mod.submit_hfl_entry.assert_not_called()
    mod.BaseApiServiceAnthropic.assert_not_called()


def test_window_timestamp_provenance_and_attachment(inbox):
    (inbox / "audio.m4a").write_bytes(b"fixture")
    path = export(inbox, attachments=["audio.m4a"])
    export(inbox, "old", captured_at="2025-01-01T10:00:00+08:00")
    result = collect()
    assert result["count"] == 1
    capture = result["captures"][0]
    assert capture["when"] == "2026-10-20T09:30:00+08:00"
    assert capture["timestamp_basis"] == "captured_at"
    assert str(path) in capture["references"]
    assert str(inbox / "audio.m4a") in capture["references"]
    assert not result["errors"]


def test_plain_markdown_uses_explicit_export_mtime(inbox):
    path = inbox / "plain.md"
    path.write_text("An unstructured export", encoding="utf-8")
    today = date.today()
    capture = mod.collect_nothing_essential_space_activity(
        since=today, until=today)["captures"][0]
    assert capture["timestamp_basis"] == "export_mtime"
    assert capture["export_text"] == "An unstructured export"


def test_duplicates_excluded_before_capture_budget(inbox):
    export(inbox, "first")
    first = collect()["captures"][0]["key"]
    export(inbox, "copy")
    export(inbox, "second", text="# Different\nAnother thought")
    result = collect(max_captures=1, exclude_keys={first})
    assert result["count"] == 1
    assert result["captures"][0]["title"] == "Different"


@pytest.mark.parametrize("metadata", [
    {"captured_at": "invalid"},
    {"attachments": ["../outside.txt"]},
    {"attachments": ["missing.wav"]},
    {"attachments": "not-a-list"},
])
def test_invalid_metadata_is_surfaced_without_reading_outside(inbox, metadata):
    export(inbox, **metadata)
    result = collect()
    assert result["count"] == 0
    assert result["errors"]


def test_size_and_scan_caps(inbox, monkeypatch):
    export(inbox)
    monkeypatch.setattr(mod, "MAX_FILE_BYTES", 5)
    assert collect()["errors"]
    assert collect(max_scan=1)["truncated"]


@pytest.mark.parametrize("delivery", ["persisted", "forwarded", "outbox"])
def test_durable_submit_and_receipts_prevent_repeat_model_call(inbox, monkeypatch, delivery):
    export(inbox)
    capture = collect()["captures"][0]
    submit = Mock(return_value={"delivery": delivery, "entry_id": "hfl-fixture",
                                "indexed": delivery == "persisted", "duplicate": False})
    monkeypatch.setattr(mod, "submit_hfl_entry", submit)
    result = run()
    assert result["entries_submitted"] == 1
    assert result["entries_written"] == int(delivery == "persisted")
    args, kwargs = submit.call_args
    assert args[0].when.isoformat() == capture["when"]
    assert args[0].references == tuple(capture["references"])
    assert kwargs == {"source": mod.SOURCE, "synthesized": False,
                      "dedup_key": f"export-v1:{capture['key']}"}
    assert result["outcomes"][0]["delivery"] == delivery
    monkeypatch.setattr(mod, "distill_nothing_essential_space_activity",
                        Mock(side_effect=AssertionError("duplicate model call")))
    assert run()["entries_submitted"] == 0
    submit.assert_called_once()


def test_failed_submission_remains_retryable(inbox, monkeypatch):
    export(inbox)
    submit = Mock(side_effect=[OSError("offline"), {"delivery": "outbox"}])
    monkeypatch.setattr(mod, "submit_hfl_entry", submit)
    assert run()["errors"]
    assert run()["entries_submitted"] == 1
    assert submit.call_count == 2


def test_edit_is_a_new_revision(inbox, monkeypatch):
    export(inbox, capture_id="same-capture")
    submit = Mock(return_value={"delivery": "persisted"})
    monkeypatch.setattr(mod, "submit_hfl_entry", submit)
    run()
    export(inbox, text="# Corrected\nRevised decision", capture_id="same-capture")
    run()
    assert submit.call_count == 2
    assert submit.call_args_list[0].kwargs["dedup_key"] != submit.call_args.kwargs["dedup_key"]


def test_mcp_backend_fails_explicitly(inbox, monkeypatch):
    monkeypatch.setenv("NOTHING_ESSENTIAL_SPACE_BACKEND", "mcp")
    with pytest.raises(NotImplementedError):
        collect()
    assert run()["skipped"] == "source unavailable"
    mod.submit_hfl_entry.assert_not_called()


def test_raw_fallback_and_invalid_model_schema(inbox, monkeypatch):
    export(inbox)
    capture = collect()["captures"][0]
    raw = mod.distill_nothing_essential_space_activity(capture, synthesize=False)
    assert raw["synthesized"] is False
    assert "may contain an AI summary" in raw["what_happened"]
    monkeypatch.setattr(mod, "get_anthropic_config", lambda _: {})
    monkeypatch.setattr(mod, "BaseApiServiceAnthropic", lambda _: SimpleNamespace(
        base_client=True, send_message=lambda **kw: SimpleNamespace(
            content=[SimpleNamespace(text='{"skip": "false", "tags": "bad"}')])))
    assert mod.distill_nothing_essential_space_activity(capture) == raw


def test_mcp_preview_does_not_write(inbox):
    from workflows.hfl.mcp import register_memory_tools

    class Registry:
        def __init__(self):
            self.tools = {}

        def tool(self, *args, **kwargs):
            def register(fn):
                self.tools[fn.__name__] = fn
                return fn
            return register

    export(inbox)
    registry = Registry()
    register_memory_tools(registry)
    result = registry.tools["nothing_essential_space_activity"](
        since=DAY.isoformat(), until=DAY.isoformat())
    assert result["found"]
    assert result["count"] == 1
    mod.submit_hfl_entry.assert_not_called()
    mod.BaseApiServiceAnthropic.assert_not_called()


@pytest.mark.skip(reason="Manual only: real exports, model and durable corpus writes")
def test_live_ingestion():
    mod.ingest_nothing_essential_space_activity(synthesize=True)
