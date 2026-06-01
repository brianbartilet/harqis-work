"""
Tests for workflows/hfl/tasks/ingest_android_apps.py.

Integration tests call the real task exactly as Beat will. The default
(no inbox directory) is a guaranteed no-op — no network, no side-effects.
Unit tests validate source resolution, privacy redaction, JSONL parsing,
per-source distillation, and the full write-path with monkeypatched IO.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import workflows.hfl.tasks.ingest_android_apps as mod
from workflows.hfl.tasks.ingest_android_apps import (
    AndroidAppSource,
    _PRIVATE_KEYS,
    _SOURCE_TAGS,
    _records_body,
    _resolve_source,
    _sanitize_metadata,
    collect_android_app_records,
    distill_android_source,
    ingest_android_app_records,
    normalize_record,
    resolve_android_inbox,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def _make_record(
    source: str = "maps",
    title: str = "Test Place",
    timestamp: str = "2026-06-01T14:00:00",
    **kwargs,
) -> dict:
    return {"source": source, "timestamp": timestamp, "title": title, **kwargs}


# ── Source resolution ─────────────────────────────────────────────────────────

def test__resolve_source_all_known_values():
    for src in AndroidAppSource:
        assert _resolve_source(src.value) == src


def test__resolve_source_case_insensitive():
    assert _resolve_source("MAPS") == AndroidAppSource.MAPS
    assert _resolve_source("Listening") == AndroidAppSource.LISTENING


def test__resolve_source_unknown_returns_none():
    assert _resolve_source("tiktok") is None
    assert _resolve_source("") is None
    assert _resolve_source(None) is None
    assert _resolve_source(42) is None


# ── Metadata sanitization ─────────────────────────────────────────────────────

def test__sanitize_metadata_strips_all_private_keys():
    raw = {k: "value" for k in _PRIVATE_KEYS}
    raw["safe_key"] = "keep me"
    clean = _sanitize_metadata(raw)
    for key in _PRIVATE_KEYS:
        assert key not in clean, f"private key '{key}' survived sanitization"
    assert clean["safe_key"] == "keep me"


def test__sanitize_metadata_non_dict_is_empty():
    assert _sanitize_metadata("text") == {}
    assert _sanitize_metadata(None) == {}
    assert _sanitize_metadata([1, 2]) == {}


def test__sanitize_metadata_gps_coordinates_stripped():
    raw = {"lat": 14.55, "lng": 121.03, "place_type": "mall"}
    clean = _sanitize_metadata(raw)
    assert "lat" not in clean
    assert "lng" not in clean
    assert clean["place_type"] == "mall"


def test__sanitize_metadata_payment_amounts_stripped():
    raw = {"amount": "500", "card": "4242", "merchant": "7-Eleven", "category": "grocery"}
    clean = _sanitize_metadata(raw)
    assert "amount" not in clean
    assert "card" not in clean
    assert clean["merchant"] == "7-Eleven"
    assert clean["category"] == "grocery"


# ── normalize_record ──────────────────────────────────────────────────────────

def test__normalize_record_full_valid():
    raw = _make_record(
        source="maps", app="Google Maps",
        metadata={"place_type": "mall"},
    )
    norm = normalize_record(raw)
    assert norm is not None
    assert norm["source"] == AndroidAppSource.MAPS
    assert norm["title"] == "Test Place"
    assert norm["app"] == "Google Maps"
    assert isinstance(norm["timestamp"], datetime)
    assert norm["tags"] == _SOURCE_TAGS[AndroidAppSource.MAPS]
    assert norm["metadata"] == {"place_type": "mall"}


def test__normalize_record_unknown_source_is_none():
    assert normalize_record(_make_record(source="unknown_app")) is None


def test__normalize_record_empty_title_is_none():
    assert normalize_record(_make_record(title="")) is None
    assert normalize_record({"source": "maps", "timestamp": "2026-06-01T10:00:00"}) is None


def test__normalize_record_bad_timestamp_falls_back_to_now():
    norm = normalize_record(_make_record(source="listening", timestamp="not-a-date"))
    assert norm is not None
    assert isinstance(norm["timestamp"], datetime)


def test__normalize_record_title_capped_at_200_chars():
    raw = _make_record(title="x" * 300)
    norm = normalize_record(raw)
    assert norm is not None
    assert len(norm["title"]) == 200


def test__normalize_record_non_dict_is_none():
    assert normalize_record("raw string") is None
    assert normalize_record(None) is None
    assert normalize_record(42) is None


def test__normalize_record_strips_private_metadata():
    raw = _make_record(
        source="payments",
        metadata={"amount": "150", "card": "1234", "merchant": "Jollibee"},
    )
    norm = normalize_record(raw)
    assert norm is not None
    assert "amount" not in norm["metadata"]
    assert "card" not in norm["metadata"]
    assert norm["metadata"]["merchant"] == "Jollibee"


def test__normalize_record_tags_are_source_specific():
    for source in AndroidAppSource:
        raw = _make_record(source=source.value)
        norm = normalize_record(raw)
        assert norm is not None
        assert norm["tags"] == _SOURCE_TAGS[source]


def test__normalize_record_app_defaults_to_source_name():
    raw = _make_record(source="browser")
    norm = normalize_record(raw)
    assert norm is not None
    assert norm["app"] == "browser"


# ── collect_android_app_records ───────────────────────────────────────────────

def test__collect_no_inbox_dir(tmp_path):
    result = collect_android_app_records(tmp_path / "missing")
    assert result["inbox_found"] is False
    assert result["records"] == []
    assert result["total_raw"] == 0


def test__collect_empty_inbox(tmp_path):
    result = collect_android_app_records(tmp_path)
    assert result["inbox_found"] is True
    assert result["records"] == []
    assert result["files_read"] == []


def test__collect_valid_jsonl(tmp_path):
    _write_jsonl(tmp_path / "android.jsonl", [
        _make_record("maps", "Greenbelt Mall", app="Google Maps"),
        _make_record("listening", "Comethru", app="YouTube Music"),
    ])
    result = collect_android_app_records(tmp_path)
    assert result["inbox_found"] is True
    assert len(result["records"]) == 2
    assert "maps" in result["by_source"]
    assert "listening" in result["by_source"]
    assert result["skipped"] == 0


def test__collect_skips_malformed_lines(tmp_path):
    (tmp_path / "mixed.jsonl").write_text(
        '{"source":"maps","timestamp":"2026-06-01T10:00:00","title":"Place A"}\n'
        "not-json\n"
        '{"source":"unknown_app","timestamp":"2026-06-01T11:00:00","title":"X"}\n'
        '{"source":"photos","timestamp":"2026-06-01T12:00:00","title":"Photo"}\n',
        encoding="utf-8",
    )
    result = collect_android_app_records(tmp_path)
    assert result["skipped"] == 2
    assert len(result["records"]) == 2
    assert result["total_raw"] == 4


def test__collect_respects_max_records(tmp_path):
    _write_jsonl(tmp_path / "many.jsonl", [
        _make_record("maps", f"Place {i}") for i in range(30)
    ])
    result = collect_android_app_records(tmp_path, max_records=10)
    assert len(result["records"]) <= 10


def test__collect_private_keys_stripped(tmp_path):
    _write_jsonl(tmp_path / "pay.jsonl", [
        _make_record("payments", "GCash payment",
                     metadata={"amount": "500", "merchant": "SM"}),
    ])
    result = collect_android_app_records(tmp_path)
    assert len(result["records"]) == 1
    assert "amount" not in result["records"][0]["metadata"]
    assert result["records"][0]["metadata"].get("merchant") == "SM"


def test__collect_multiple_files(tmp_path):
    _write_jsonl(tmp_path / "a.jsonl", [_make_record("maps", "Place A")])
    _write_jsonl(tmp_path / "b.jsonl", [_make_record("browser", "Article link")])
    result = collect_android_app_records(tmp_path)
    assert len(result["records"]) == 2
    assert len(result["files_read"]) == 2


def test__collect_by_source_grouping(tmp_path):
    _write_jsonl(tmp_path / "data.jsonl", [
        _make_record("listening", "Track A"),
        _make_record("listening", "Track B"),
        _make_record("maps", "Place X"),
    ])
    result = collect_android_app_records(tmp_path)
    assert len(result["by_source"]["listening"]) == 2
    assert len(result["by_source"]["maps"]) == 1


# ── distill_android_source ────────────────────────────────────────────────────

def _fake_records(source: str, count: int = 2) -> list[dict]:
    src = AndroidAppSource(source)
    return [
        {
            "source":    src,
            "app":       source.title(),
            "timestamp": datetime(2026, 6, 1, 10 + i),
            "title":     f"{source.title()} item {i}",
            "metadata":  {},
            "tags":      list(_SOURCE_TAGS[src]),
        }
        for i in range(count)
    ]


def test__distill_android_source_required_fields():
    d = distill_android_source("maps", _fake_records("maps"))
    for key in ("source", "moment", "what_happened", "why_it_stayed",
                "possible_use", "tags", "references", "record_count"):
        assert key in d, f"missing key: {key}"


def test__distill_android_source_moment_capped_at_200():
    records = _fake_records("listening", 10)
    d = distill_android_source("listening", records)
    assert len(d["moment"]) <= 200


def test__distill_android_source_correct_tags():
    for source in AndroidAppSource:
        d = distill_android_source(source.value, _fake_records(source.value, 1))
        assert d["tags"] == _SOURCE_TAGS[source]


def test__distill_android_source_record_count():
    d = distill_android_source("browser", _fake_records("browser", 5))
    assert d["record_count"] == 5


def test__distill_android_source_titles_in_body():
    records = _fake_records("photos", 3)
    d = distill_android_source("photos", records)
    assert "Photos item 0" in d["moment"] or "Photos item 0" in d["what_happened"]


def test__distill_android_source_all_sources_smoke():
    for source in AndroidAppSource:
        d = distill_android_source(source.value, _fake_records(source.value, 1))
        assert isinstance(d["moment"], str) and d["moment"]
        assert isinstance(d["what_happened"], str) and d["what_happened"]


# ── _records_body ─────────────────────────────────────────────────────────────

def test__records_body_includes_title_and_timestamp():
    records = [
        {"source": AndroidAppSource.MAPS, "app": "Maps",
         "timestamp": datetime(2026, 6, 1, 14, 30),
         "title": "Greenbelt Mall", "metadata": {"place_type": "mall"}, "tags": []},
    ]
    body = _records_body("maps", records)
    assert "Greenbelt Mall" in body
    assert "2026-06-01 14:30" in body
    assert "place_type=mall" in body


def test__records_body_caps_at_40_items():
    records = [
        {"source": AndroidAppSource.BROWSER, "app": "Chrome",
         "timestamp": datetime(2026, 6, 1) + timedelta(minutes=i),
         "title": f"Article {i}", "metadata": {}, "tags": []}
        for i in range(50)
    ]
    body = _records_body("browser", records)
    assert body.count("- [") == 40


# ── resolve_android_inbox ─────────────────────────────────────────────────────

def test__resolve_android_inbox_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("HFL_ANDROID_INBOX_PATH", str(tmp_path))
    assert resolve_android_inbox() == tmp_path.resolve()


def test__resolve_android_inbox_default_fallback(monkeypatch):
    monkeypatch.delenv("HFL_ANDROID_INBOX_PATH", raising=False)
    p = resolve_android_inbox()
    assert p.name == "hfl-android-inbox"
    assert "logs" in str(p)


# ── Integration / full task ───────────────────────────────────────────────────

def test__ingest_android_app_records_no_inbox(monkeypatch, tmp_path):
    """No inbox directory → clean no-op."""
    monkeypatch.setattr(mod, "resolve_android_inbox", lambda: tmp_path / "missing")
    result = ingest_android_app_records()
    assert result["entries_written"] == 0
    assert result["skipped"] == "inbox not found"


def test__ingest_android_app_records_empty_inbox(monkeypatch, tmp_path):
    """Empty inbox directory → clean no-op."""
    monkeypatch.setattr(mod, "resolve_android_inbox", lambda: tmp_path)
    result = ingest_android_app_records()
    assert result["entries_written"] == 0
    assert result["skipped"] == "no records"


def test__ingest_android_app_records_one_entry_per_source(monkeypatch, tmp_path):
    """One HFL entry is written per active source."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    _write_jsonl(inbox / "android.jsonl", [
        _make_record("maps", "Greenbelt Mall"),
        _make_record("listening", "Track A"),
        _make_record("listening", "Track B"),
    ])

    monkeypatch.setattr(mod, "resolve_android_inbox", lambda: inbox)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: corpus)

    append_calls: list[dict] = []
    real_append = mod.append_entry

    def _capture_append(day_file, entry, *, source, synthesized=False):
        append_calls.append({"source": source})
        return real_append(day_file, entry, source=source, synthesized=synthesized)

    monkeypatch.setattr(mod, "append_entry", _capture_append)

    result = ingest_android_app_records()

    assert result["entries_written"] == 2
    sources = {c["source"] for c in append_calls}
    assert "android:maps" in sources
    assert "android:listening" in sources
    assert result["by_source"]["maps"] == 1
    assert result["by_source"]["listening"] == 2
    assert result["records"] == 3


def test__ingest_android_app_records_corpus_file_written(monkeypatch, tmp_path):
    """The corpus Markdown file is created and non-empty."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    _write_jsonl(inbox / "share.jsonl", [_make_record("browser", "Article link")])

    monkeypatch.setattr(mod, "resolve_android_inbox", lambda: inbox)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: corpus)

    result = ingest_android_app_records()
    assert result["entries_written"] == 1

    day_file = Path(result["path"])
    assert day_file.exists()
    content = day_file.read_text(encoding="utf-8")
    assert "Article link" in content
    assert "#browsing" in content or "#android" in content


def test__ingest_android_app_records_clear_after(monkeypatch, tmp_path):
    """clear_after=True moves processed JSONL files to done/."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    _write_jsonl(inbox / "share.jsonl", [_make_record("browser", "Saved article")])

    monkeypatch.setattr(mod, "resolve_android_inbox", lambda: inbox)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: corpus)

    result = ingest_android_app_records(clear_after=True)
    assert result["entries_written"] == 1
    assert not (inbox / "share.jsonl").exists()
    assert (inbox / "done" / "share.jsonl").exists()


def test__ingest_android_app_records_all_sources_write(monkeypatch, tmp_path):
    """Every supported source produces exactly one entry."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()

    records = [
        _make_record(src.value, f"{src.value} title")
        for src in AndroidAppSource
    ]
    _write_jsonl(inbox / "all.jsonl", records)

    monkeypatch.setattr(mod, "resolve_android_inbox", lambda: inbox)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: corpus)

    result = ingest_android_app_records()
    assert result["entries_written"] == len(AndroidAppSource)
    for src in AndroidAppSource:
        assert src.value in result["by_source"]
