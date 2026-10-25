"""Synthetic integration contracts; no live corpus, broker, model, or network."""
import asyncio
import json
from dataclasses import asdict
from datetime import date
from types import SimpleNamespace

import pytest

from apps.granola.references.dto.note import DtoGranolaNote
from apps.granola.references.web.api.notes import ApiServiceGranolaNotes
from apps.granola.references.web.base_api_service import GranolaApiError
from workflows.hfl.tasks import ingest_granola as mod

NOTE_ID = "not_1d3tmYTlCICgjy"
OTHER_ID = "not_2d3tmYTlCICgjy"
FOLDER = "fol_4y6LduVdwSKC27"
DAY = date(2026, 10, 20)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import requests
    import core.apps.es_logging.app.elasticsearch as elastic
    monkeypatch.setattr(elastic, "_ES_CONFIGURED", False)
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "")
    monkeypatch.delenv("GRANOLA_FOLDER_ID", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network/model/persistence")
    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(mod, "BaseApiServiceAnthropic", forbidden)
    monkeypatch.setattr(mod, "submit_hfl_entry", forbidden)


def note(**kwargs):
    return DtoGranolaNote(**{
        "id": NOTE_ID, "title": "Migration review", "created_at": "2026-10-20T02:00:00Z",
        "updated_at": "2026-10-20T03:00:00Z",
        "summary_markdown": "Brian will prepare a test plan.",
        "private_notes_text": "Private material must not be ingested",
        "calendar_event": {"scheduled_start_time": "2026-10-19T02:00:00Z"},
        "web_url": "https://notes.granola.ai/d/example", **kwargs,
    })


class Source:
    def __init__(self, pages, notes=None):
        self.pages = iter(pages)
        self.notes = notes or {NOTE_ID: note()}
        self.calls = []
    def list_notes(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.pages)
    def get_note(self, identity):
        value = self.notes[identity]
        if isinstance(value, Exception):
            raise value
        return value


def collected(source=None, **kwargs):
    source = source or Source([{"notes": [{"id": NOTE_ID}], "hasMore": False}])
    return mod.collect_granola_activity(since=DAY, until=DAY, folder_id=FOLDER, service=source, **kwargs)


def test__ingest_no_credentials():
    assert mod.ingest_granola_activity()["skipped"] == "no token"


def test__ingest_no_folder(monkeypatch):
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "test-only")
    assert mod.ingest_granola_activity()["skipped"] == "no folder"


def test__ingest_empty_window(monkeypatch):
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "test-only")
    monkeypatch.setattr(mod, "ApiServiceGranolaNotes", lambda _: Source([{"notes": [], "hasMore": False}]))
    result = mod.ingest_granola_activity(folder_id=FOLDER, since=str(DAY), until=str(DAY))
    assert result["skipped"] == "no notes"
    assert result["entries_submitted"] == 0


@pytest.mark.skip(reason="Manual only: calls Granola/Anthropic and writes real HFL entries")
def test__ingest_live():
    mod.ingest_granola_activity()


@pytest.mark.parametrize("delivery,duplicate,written", [
    ("persisted", False, 1), ("persisted", True, 0),
    ("forwarded", False, 0), ("outbox", False, 0),
])
def test__ingest_durable_contract(monkeypatch, delivery, duplicate, written):
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "test-only")
    monkeypatch.setattr(mod, "ApiServiceGranolaNotes", lambda _: Source([{"notes": [{"id": NOTE_ID}], "hasMore": False}]))
    calls = []
    def submit(entry, **kwargs):
        calls.append((entry, kwargs))
        return {"delivery": delivery, "duplicate": duplicate, "indexed": delivery == "persisted",
                "entry_id": "hfl-test"}
    monkeypatch.setattr(mod, "submit_hfl_entry", submit)
    result = mod.ingest_granola_activity(folder_id=FOLDER, since=str(DAY), until=str(DAY), synthesize=False)
    assert len(calls) == 1
    entry, kwargs = calls[0]
    assert kwargs == {"source": "granola", "synthesized": True, "dedup_key": f"granola:{NOTE_ID}"}
    assert entry.when.date() == DAY
    assert "2026-10-19T10:00:00+08:00" in entry.what_happened
    assert "Private material" not in entry.what_happened
    assert entry.references == ("https://notes.granola.ai/d/example",)
    assert result["entries_written"] == written
    assert result["results"][0]["delivery"] == delivery


def test__collector_pages_and_exact_midnight():
    source = Source([
        {"notes": [{"id": NOTE_ID}], "hasMore": True, "cursor": "next"},
        {"notes": [{"id": OTHER_ID}], "hasMore": False},
    ], {NOTE_ID: note(created_at="2026-10-19T16:00:00Z"),
        OTHER_ID: note(id=OTHER_ID, created_at="2026-10-20T16:00:00Z")})
    result = collected(source)
    assert [n["id"] for n in result["notes"]] == [NOTE_ID]
    assert source.calls[1]["cursor"] == "next"
    assert source.calls[0]["created_after"] < "2026-10-19T16:00:00"
    assert not result["partial"]


def test__collector_cap_and_failed_detail_resume():
    source = Source([{"notes": [{"id": NOTE_ID}], "hasMore": True, "cursor": "more"}])
    result = collected(source, max_notes=1)
    assert result["partial"] and result["next_cursor"] == "more"
    source = Source([{"notes": [{"id": NOTE_ID}], "hasMore": True, "cursor": "more"}],
                    {NOTE_ID: GranolaApiError(429)})
    result = collected(source, cursor="page-start")
    assert result["partial"] and result["next_cursor"] == "page-start"
    assert result["errors"] == ["GranolaApiError"]


def test__collector_deleted_empty_invalid_and_truncated():
    for value in (note(deleted_at="2026-10-20"), note(summary_markdown=""), note(created_at="bad")):
        assert not collected(Source([{"notes": [{"id": NOTE_ID}], "hasMore": False}],
                                    {NOTE_ID: value}))["notes"]
    result = collected(Source([{"notes": [{"id": NOTE_ID}], "hasMore": False}],
                              {NOTE_ID: note(summary_markdown="x" * 31000)}))
    assert result["notes"][0]["truncated"]
    assert len(result["notes"][0]["summary"]) == 30000


def test__collector_duplicate_and_repeated_cursor():
    result = collected(Source([
        {"notes": [{"id": NOTE_ID}], "hasMore": True, "cursor": "repeat"},
        {"notes": [{"id": NOTE_ID}], "hasMore": True, "cursor": "repeat"},
    ]))
    assert len(result["notes"]) == 1
    assert result["partial"] and result["errors"] == ["RepeatedCursor"]


@pytest.mark.parametrize("body", [
    {}, {"skip": "false"}, {"skip": False, "moment": [], "tags": "meeting"},
])
def test__malformed_model_falls_back(monkeypatch, body):
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(body))])
    monkeypatch.setattr(mod, "BaseApiServiceAnthropic", lambda _: SimpleNamespace(send_message=lambda **_: response))
    assert not mod.distill_granola_activity(collected()["notes"][0])["distilled"]


def test__valid_model_and_skip(monkeypatch):
    body = {"skip": False, "moment": "Review", "what_happened": "A test plan was discussed.",
            "why_it_stayed": "", "possible_use": "meeting-recall", "tags": ["meeting", "qa"]}
    def generate(**kwargs):
        assert kwargs["model"] == mod._DEFAULT_HAIKU
        assert "untrusted data" in kwargs["system"]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(body))])
    monkeypatch.setattr(mod, "BaseApiServiceAnthropic", lambda _: SimpleNamespace(send_message=generate))
    assert mod.distill_granola_activity(collected()["notes"][0])["distilled"]
    body["skip"] = True
    assert mod.distill_granola_activity(collected()["notes"][0])["skip"]


def test__transport_and_typed_note(monkeypatch):
    import requests
    calls = []
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def json(self): return asdict(note())
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "test-only")
    service = ApiServiceGranolaNotes(mod.CONFIG)
    assert service.get_note(NOTE_ID).id == NOTE_ID
    assert calls[0][0] == f"https://public-api.granola.ai/v1/notes/{NOTE_ID}"
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-only"
    with pytest.raises(ValueError):
        service.get_note("../../secret")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 413, 429, 503])
def test__transport_http_error_redacted(monkeypatch, status):
    import requests
    class Response:
        status_code = status
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(requests, "get", lambda *_, **__: Response())
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "test-only")
    with pytest.raises(GranolaApiError, match=f"HTTP {status}"):
        ApiServiceGranolaNotes(mod.CONFIG).list_notes()


def test__page_validation_and_bounds(monkeypatch):
    from apps.granola.references.web.api.notes import page
    for payload in ({}, {"notes": [], "hasMore": True, "cursor": ""}):
        with pytest.raises(ValueError):
            page(payload, "notes")
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "test-only")
    service = ApiServiceGranolaNotes(mod.CONFIG)
    with pytest.raises(ValueError):
        service.list_folders(page_size=31)
    with pytest.raises(ValueError):
        service.get_transcript(NOTE_ID, page_size=101)
    source = Source([{"notes": [{"id": NOTE_ID}, {"id": OTHER_ID}], "hasMore": False}])
    result = collected(source, max_notes=1)
    assert result["partial"] and not result["notes"]


def test__persistence_failure_is_visible(monkeypatch):
    monkeypatch.setitem(mod.CONFIG.app_data, "api_key", "test-only")
    monkeypatch.setattr(mod, "ApiServiceGranolaNotes", lambda _: Source([{"notes": [{"id": NOTE_ID}], "hasMore": False}]))
    def fail(*args, **kwargs):
        raise OSError("private path must not appear")
    monkeypatch.setattr(mod, "submit_hfl_entry", fail)
    result = mod.ingest_granola_activity(folder_id=FOLDER, since=str(DAY), until=str(DAY), synthesize=False)
    assert result["partial"] and result["entries_written"] == 0
    assert result["results"][0]["error"] == "OSError"
    assert "private path" not in json.dumps(result)


def test__tools_and_preview_no_write(monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from apps.granola.mcp import register_granola_tools
    from workflows.hfl.mcp import register_memory_tools
    server = FastMCP("granola-test")
    register_granola_tools(server)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"list_granola_notes", "get_granola_note", "get_granola_transcript", "list_granola_folders"}
    class Registry:
        def __init__(self): self.tools = {}
        def tool(self):
            def decorate(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorate
    registry = Registry()
    register_memory_tools(registry)
    result = registry.tools["granola_activity"](since=str(DAY), until=str(DAY), folder_id=FOLDER)
    assert not result["found"] and result["skipped"] == "no token"
    snapshot = collected()
    monkeypatch.setattr(mod, "collect_granola_activity", lambda **_: snapshot)
    result = registry.tools["granola_activity"](since=str(DAY), until=str(DAY), folder_id=FOLDER)
    assert result["found"] and not result["previews"][0]["distilled"]
