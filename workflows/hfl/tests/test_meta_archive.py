"""Synthetic-only tests for the manual Meta archive importer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from workflows.hfl.dto import HflEntry
from workflows.hfl.meta_archive.models import MetaEvent
from workflows.hfl.meta_archive.parsers import parse_facebook_thread, parse_instagram_html
from workflows.hfl.meta_archive.planner import build_import_plan
from workflows.hfl.tasks import ingest_meta_archive as module


def _facebook_export(root: Path) -> tuple[Path, Path]:
    export = root / "facebook-owner-2026-test"
    thread = export / "your_facebook_activity" / "messages" / "inbox" / "friend_1"
    thread.mkdir(parents=True)
    path = thread / "message_1.json"
    path.write_text(json.dumps({
        "participants": [{"name": "Owner"}, {"name": "Friend"}],
        "title": "Friend", "thread_path": "inbox/friend_1",
        "messages": [{
            "sender_name": "Owner", "timestamp_ms": 1717372800000,
            "content": "Confirmed the Saturday plan.",
            "photos": [{"uri": "missing/photo.jpg"}],
        }],
    }), encoding="utf-8")
    return export, path


def test__parse_facebook_thread_structure(tmp_path):
    export, path = _facebook_export(tmp_path)
    events = parse_facebook_thread(path, export)
    assert len(events) == 1
    assert events[0].platform == "facebook"
    assert events[0].thread_id == "inbox/friend_1"
    assert events[0].content == "Confirmed the Saturday plan."
    assert events[0].references[0].startswith("meta-archive://facebook/")


def test__parse_instagram_html_structure(tmp_path):
    export = tmp_path / "instagram-owner-2026-test"
    thread = export / "your_instagram_activity" / "messages" / "inbox" / "friend_2"
    thread.mkdir(parents=True)
    path = thread / "message_1.html"
    path.write_text("""<html><head><title>Friend Two</title></head><body>
    <div class="pam _3-95"><h2>Owner</h2><div class="_3-95 _a6-p">A useful message</div>
    <div class="_3-94 _a6-o">Jun 03, 2024 9:30 pm</div></div></body></html>""", encoding="utf-8")
    events = parse_instagram_html(path, export, thread_id="friend_2")
    assert len(events) == 1
    assert events[0].platform == "instagram"
    assert events[0].occurred_at_local.tzinfo is not None
    assert events[0].content == "A useful message"


def test__build_import_plan_deduplicates_overlapping_parts(tmp_path):
    meta = tmp_path / "meta-download"
    export, source = _facebook_export(meta)
    duplicate = source.with_name("message_2.json")
    duplicate.write_bytes(source.read_bytes())
    plan = build_import_plan(
        platform="facebook", archive_roots=[str(meta), str(meta)],
        work_dir=str(tmp_path / "work"),
    )
    assert plan["ok"] is True
    assert plan["events_discovered"] == 1
    assert plan["work_item_count"] == 1
    assert Path(plan["manifest_path"]).exists()


def test__ingest_meta_work_item_submits_exactly_once(tmp_path, monkeypatch):
    event = MetaEvent(
        platform="facebook", thread_id="friend", thread_title="Friend",
        participants=("Owner", "Friend"), sender="Owner",
        occurred_at_utc=datetime(2024, 6, 3, 13, 30, tzinfo=timezone.utc),
        occurred_at_local=datetime.fromisoformat("2024-06-03T21:30:00+08:00"),
        event_type="message", content="Confirmed the plan.",
        references=("meta-archive://facebook/test/message_1.json",),
    )
    path = tmp_path / "item.json"
    path.write_text(json.dumps({
        "platform": "facebook", "thread_id": "friend",
        "week_start": "2024-06-03", "events": [event.to_dict()],
    }), encoding="utf-8")
    calls = []
    monkeypatch.setattr(module, "submit_hfl_entry", lambda *args, **kwargs: calls.append((args, kwargs)) or {
        "delivery": "persisted", "entry_id": "test-id", "indexed": True,
    })
    result = module.ingest_meta_work_item(
        work_item_path=str(path), platform="facebook", allow_cloud=False,
        synthesize=False,
    )
    assert result["entries_written"] == 1
    assert len(calls) == 1
    assert calls[0][1]["source"] == "facebook"
    assert calls[0][1]["dedup_key"] == "facebook:friend:2024-06-03"


def test__references_render_in_activity_corpus():
    entry = HflEntry(
        when=datetime(2024, 6, 3), moment="A remembered conversation",
        references=("meta-archive://facebook/test/message_1.json",),
    )
    rendered = entry.to_markdown()
    assert "References:" in rendered
    assert "meta-archive://facebook/test/message_1.json" in rendered
