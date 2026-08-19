"""Synthetic-only tests for the manual Meta archive importer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from workflows.hfl import persistence
from workflows.hfl.dto import HflEntry
from workflows.hfl.meta_archive import enrichment
from workflows.hfl.meta_archive.models import MetaAttachment, MetaEvent
from workflows.hfl.meta_archive.parsers import (
    parse_facebook_posts,
    parse_facebook_thread,
    parse_instagram_html,
)
from workflows.hfl.meta_archive.planner import build_import_plan, content_sha256
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


def _event(*, platform: str = "facebook", event_type: str = "message",
           content: str = "Confirmed the plan.", minute: int = 30,
           attachments: tuple[MetaAttachment, ...] = ()) -> MetaEvent:
    return MetaEvent(
        platform=platform, thread_id="friend", thread_title="Friend",
        participants=("Owner", "Friend"), sender="Owner",
        occurred_at_utc=datetime(2024, 6, 3, 13, minute, tzinfo=timezone.utc),
        occurred_at_local=datetime.fromisoformat(
            f"2024-06-03T21:{minute:02d}:00+08:00"
        ),
        event_type=event_type, content=content, attachments=attachments,
        references=(f"meta-archive://{platform}/test/source",),
    )


def _write_work_item(path: Path, events: list[MetaEvent], *,
                     platform: str = "facebook") -> str:
    content = json.dumps({
        "schema_version": 1, "platform": platform, "thread_id": "friend",
        "week_start": "2024-06-03", "events": [event.to_dict() for event in events],
    }, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(content)
    return content_sha256(content)


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


def test__parse_authored_facebook_and_instagram_content(tmp_path):
    facebook = tmp_path / "facebook-owner-2026-test"
    facebook.mkdir()
    fb_path = facebook / "posts.json"
    fb_path.write_text(json.dumps([{
        "timestamp": 1717372800,
        "data": [{"post": "A post worth retaining"}],
        "attachments": [],
    }]), encoding="utf-8")
    fb_events = parse_facebook_posts(fb_path, facebook)
    assert len(fb_events) == 1
    assert fb_events[0].event_type == "authored-content"
    assert fb_events[0].content == "A post worth retaining"

    instagram = tmp_path / "instagram-owner-2026-test"
    instagram.mkdir()
    media = instagram / "photo.jpg"
    media.write_bytes(b"synthetic image")
    ig_path = instagram / "posts_1.html"
    ig_path.write_text("""<html><body><div class="pam"><h2>Owner</h2>
    <div class="_a6-p">An authored post</div><img src="photo.jpg">
    <div>Jun 03, 2024 9:30 pm</div></div></body></html>""", encoding="utf-8")
    ig_events = parse_instagram_html(
        ig_path, instagram, thread_id="authored-content", authored=True
    )
    assert len(ig_events) == 1
    assert ig_events[0].event_type == "authored-content"
    assert ig_events[0].attachments[0].path == str(media.resolve())


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
    assert len(plan["manifest_sha256"]) == 64
    assert len(plan["items"][0]["sha256"]) == 64


def test__ingest_meta_work_item_submits_exactly_once(tmp_path, monkeypatch):
    event = _event()
    path = tmp_path / "item.json"
    digest = _write_work_item(path, [event])
    calls = []
    monkeypatch.setattr(module, "submit_hfl_entry", lambda *args, **kwargs: calls.append((args, kwargs)) or {
        "delivery": "persisted", "entry_id": "test-id", "indexed": True,
    })
    result = module.ingest_meta_work_item(
        work_item_path=str(path), platform="facebook", allow_cloud=False,
        synthesize=False, expected_work_item_sha256=digest,
        work_item_root=str(tmp_path),
    )
    assert result["entries_written"] == 1
    assert len(calls) == 1
    assert calls[0][1]["source"] == "facebook"
    assert calls[0][1]["dedup_key"] == "facebook:friend:2024-06-03"
    assert calls[0][1]["replace_duplicate"] is True
    assert calls[0][0][0].when.isoformat() == "2024-06-03T00:00:00+08:00"


def test__instagram_conversation_media_never_reaches_cloud(tmp_path, monkeypatch):
    media = tmp_path / "private.m4a"
    media.write_bytes(b"private")
    attachment = MetaAttachment(
        kind="audio", path=str(media), media_id="private-media",
        reference="meta-archive://instagram/test/private.m4a",
    )
    event = _event(platform="instagram", attachments=(attachment,))
    monkeypatch.setattr(
        enrichment, "get_anthropic_config",
        lambda *_: (_ for _ in ()).throw(AssertionError("cloud config accessed")),
    )
    monkeypatch.setattr(
        enrichment, "_transcribe_with_whisper",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Whisper called")),
    )

    assert enrichment.enrich_event_media(
        [event], allow_cloud=True, cache_dir=str(tmp_path / "cache")
    ) == {}


def test__eligible_media_enrichment_uses_content_cache(tmp_path, monkeypatch):
    media = tmp_path / "authored.m4a"
    media.write_bytes(b"authored")
    attachment = MetaAttachment(
        kind="audio", path=str(media), media_id="authored-media",
        reference="meta-archive://instagram/test/authored.m4a",
    )
    event = _event(
        platform="instagram", event_type="authored-content",
        attachments=(attachment,),
    )
    calls = []

    class Client:
        base_client = None

    monkeypatch.setattr(enrichment, "get_anthropic_config", lambda *_: {})
    monkeypatch.setattr(enrichment, "BaseApiServiceAnthropic", lambda *_: Client())
    monkeypatch.setattr(
        enrichment, "_transcribe_with_whisper",
        lambda *_a, **_k: calls.append("transcribe") or "cached transcript",
    )
    cache = tmp_path / "cache"
    first = enrichment.enrich_event_media([event], allow_cloud=True, cache_dir=str(cache))
    second = enrichment.enrich_event_media([event], allow_cloud=True, cache_dir=str(cache))

    assert first == second
    assert first["authored-media"]["transcript"] == "cached transcript"
    assert calls == ["transcribe"]


def test__dispatch_requires_pinned_manifest_and_work_items(tmp_path, monkeypatch):
    export_root = tmp_path / "exports"
    _facebook_export(export_root)
    plan = build_import_plan(
        platform="facebook", archive_roots=[str(export_root)],
        work_dir=str(tmp_path / "work"),
    )
    sent = []

    class Result:
        id = "task-1"

    monkeypatch.setattr(
        module.SPROUT, "send_task",
        lambda *args, **kwargs: sent.append((args, kwargs)) or Result(),
    )
    result = module.dispatch_meta_archive_import(
        manifest_path=plan["manifest_path"],
        approved_manifest_sha256=plan["manifest_sha256"],
    )
    assert result["dispatched"] == 1
    assert result["allow_cloud"] is False
    assert sent[0][1]["kwargs"]["expected_work_item_sha256"] == plan["items"][0]["sha256"]

    item_path = Path(plan["items"][0]["path"])
    item_path.write_bytes(item_path.read_bytes() + b" ")
    rejected = module.dispatch_meta_archive_import(
        manifest_path=plan["manifest_path"],
        approved_manifest_sha256=plan["manifest_sha256"],
    )
    assert rejected["dispatched"] == 0
    assert "work item integrity" in rejected["error"]

    manifest_path = Path(plan["manifest_path"])
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    rejected = module.dispatch_meta_archive_import(
        manifest_path=str(manifest_path),
        approved_manifest_sha256=plan["manifest_sha256"],
    )
    assert rejected["dispatched"] == 0
    assert "manifest integrity" in rejected["error"]


def test__dispatch_rejects_cross_root_and_malformed_work_items(tmp_path, monkeypatch):
    export_root = tmp_path / "exports"
    _facebook_export(export_root)
    plan = build_import_plan(
        platform="facebook", archive_roots=[str(export_root)],
        work_dir=str(tmp_path / "work"),
    )
    manifest_path = Path(plan["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    external = tmp_path / "outside.json"
    digest = _write_work_item(external, [_event()])
    manifest["items"][0].update(path=str(external), sha256=digest)
    content = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_path.write_bytes(content)
    rejected = module.dispatch_meta_archive_import(
        manifest_path=str(manifest_path),
        approved_manifest_sha256=content_sha256(content),
    )
    assert rejected["dispatched"] == 0
    assert "outside the approved" in rejected["error"]

    local_item = manifest_path.parent / "malformed.json"
    digest = _write_work_item(local_item, [_event()], platform="instagram")
    manifest["items"][0].update(path=str(local_item), sha256=digest, thread_id="friend")
    content = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_path.write_bytes(content)
    monkeypatch.setattr(
        module.SPROUT, "send_task",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must fail before dispatch")),
    )
    rejected = module.dispatch_meta_archive_import(
        manifest_path=str(manifest_path),
        approved_manifest_sha256=content_sha256(content),
    )
    assert rejected["dispatched"] == 0
    assert "platform mismatch" in rejected["error"]


def test__overlapping_replay_keeps_markdown_and_es_in_parity(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    indexed = []
    monkeypatch.setattr(persistence, "outbox_dir", lambda: tmp_path / "outbox")
    monkeypatch.setattr(persistence, "local_machine_name", lambda: "harqis-server")
    monkeypatch.setattr(persistence, "is_canonical_machine", lambda machine=None: True)
    monkeypatch.setattr(
        "workflows.hfl.tasks.capture.resolve_corpus_dir", lambda: corpus
    )
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: indexed.append((entry, kwargs)) or kwargs["doc_id"],
    )
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first = _event(content="The first event", minute=10)
    later = _event(content="A later overlapping-export event", minute=20)
    _write_work_item(first_path, [first])
    _write_work_item(second_path, [first, later])

    module.ingest_meta_work_item(
        work_item_path=str(first_path), platform="facebook",
        allow_cloud=False, synthesize=False,
    )
    module.ingest_meta_work_item(
        work_item_path=str(second_path), platform="facebook",
        allow_cloud=False, synthesize=False,
    )

    text = (corpus / "2024-06-03.md").read_text(encoding="utf-8")
    entries = tuple(persistence._entry_blocks(text))
    assert len(entries) == 1
    assert "later overlapping-export event" in entries[0].what_happened
    assert indexed[-1][0].entry_id == entries[0].entry_id
    assert indexed[-1][0].moment == entries[0].moment
    assert indexed[-1][0].what_happened == entries[0].what_happened
    assert indexed[-1][0].references == entries[0].references
    assert indexed[0][1]["doc_id"] == indexed[-1][1]["doc_id"]


def test__references_render_in_activity_corpus():
    entry = HflEntry(
        when=datetime(2024, 6, 3), moment="A remembered conversation",
        references=("meta-archive://facebook/test/message_1.json",),
    )
    rendered = entry.to_markdown()
    assert "References:" in rendered
    assert "meta-archive://facebook/test/message_1.json" in rendered
