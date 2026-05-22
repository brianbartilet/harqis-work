"""
Tests for workflows/hfl/tasks/time_capsule.py.

The whole `workflows/` tree is excluded from the default pytest run
(`addopts = --ignore=workflows/` in pytest.ini), so these only execute when
targeted explicitly:

    pytest workflows/hfl/tests/test_time_capsule.py -v
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from workflows.hfl.tasks import time_capsule as tc
from workflows.hfl.tasks.time_capsule import (
    parse_period,
    collect_archive,
    render_digest,
    run_collect,
    run_write,
    _classify,
    _slug,
    Window,
)


# ── Period parsing ────────────────────────────────────────────────────────────

def test__parse_month_year():
    w = parse_period("May 2020")
    assert w.start == datetime(2020, 5, 1)
    assert w.end == datetime(2020, 6, 1)
    assert w.label == "2020-05" or "2020" in w.label


def test__parse_single_day_long_form():
    w = parse_period("August 1, 2002")
    assert w.start == datetime(2002, 8, 1)
    assert w.end == datetime(2002, 8, 2)


def test__parse_single_day_iso():
    w = parse_period("2019-06-15")
    assert w.start == datetime(2019, 6, 15)
    assert w.end == datetime(2019, 6, 16)


def test__parse_month_range_shared_year():
    w = parse_period("June-July 2019")
    assert w.start == datetime(2019, 6, 1)
    assert w.end == datetime(2019, 8, 1)   # end-exclusive: first of August


def test__parse_iso_range_inclusive_end():
    w = parse_period("2019-06-01..2019-07-31")
    assert w.start == datetime(2019, 6, 1)
    assert w.end == datetime(2019, 8, 1)   # inclusive 07-31 → exclusive 08-01


def test__parse_since_today():
    now = datetime(2026, 5, 23, 10, 0)
    w = parse_period("since 2020-01-01", now=now)
    assert w.start == datetime(2020, 1, 1)
    assert w.end == now


def test__parse_relative_days():
    now = datetime(2026, 5, 23, 10, 0)
    w = parse_period("last 30 days", now=now)
    assert (w.end - w.start).days == 30
    assert w.end == now


def test__parse_whole_year():
    w = parse_period("2019")
    assert w.start == datetime(2019, 1, 1)
    assert w.end == datetime(2020, 1, 1)


def test__parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_period("not a date")
    with pytest.raises(ValueError):
        parse_period("")


# ── Classification / slug ───────────────────────────────────────────────────

def test__classify_buckets():
    assert _classify(".txt") == "text"
    assert _classify(".LOG") == "text"
    assert _classify(".png") == "image"
    assert _classify(".mp4") == "video"
    assert _classify(".mp3") == "audio"
    assert _classify(".pdf") == "document"
    assert _classify(".bin") == "other"


def test__slug_is_filename_safe():
    assert _slug("2019-06") == "2019-06"
    assert _slug("Jun-Jul 2019!!") == "jun-jul-2019"


# ── Collection (text only — no Anthropic, no network) ─────────────────────────

def _touch(path: Path, content: str, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def test__collect_archive_windows_by_mtime(tmp_path: Path):
    # Two files inside May 2020, one outside (June) — only the two count.
    _touch(tmp_path / "notes" / "a.txt", "Project kickoff with Acme.", datetime(2020, 5, 3, 9, 0))
    _touch(tmp_path / "b.log", "ERROR: disk full on host-7", datetime(2020, 5, 20, 14, 0))
    _touch(tmp_path / "c.txt", "out of window", datetime(2020, 6, 10, 9, 0))

    w = parse_period("May 2020")
    manifest = collect_archive(tmp_path, w, do_caption=False)

    assert manifest["counts"]["total_in_window"] == 2
    assert manifest["counts"]["analyzed"] == 2
    assert manifest["counts"]["by_kind"].get("text") == 2
    texts = " ".join(f.get("text") or "" for f in manifest["files"])
    assert "Acme" in texts and "disk full" in texts
    # by_day has both May days, not the June one.
    assert set(manifest["by_day"]) == {"2020-05-03", "2020-05-20"}


def test__collect_archive_empty_window(tmp_path: Path):
    _touch(tmp_path / "a.txt", "x", datetime(2020, 5, 3, 9, 0))
    w = parse_period("January 2019")
    manifest = collect_archive(tmp_path, w, do_caption=False)
    assert manifest["counts"]["total_in_window"] == 0
    assert manifest["files"] == []


def test__collect_degrades_on_document_and_audio(tmp_path: Path):
    # A junk .pdf (no/failed parser) and an .mp3 (no transcriber) must be
    # recorded metadata-only with a note — never crash the sweep.
    _touch(tmp_path / "scan.pdf", "%PDF-1.4 not-a-real-pdf", datetime(2020, 5, 4, 9, 0))
    _touch(tmp_path / "memo.mp3", "ID3 binary-ish", datetime(2020, 5, 4, 10, 0))
    w = parse_period("May 2020")
    manifest = collect_archive(tmp_path, w, do_caption=False)

    assert manifest["counts"]["analyzed"] == 2
    assert manifest["counts"]["errored"] == 0
    by_kind = manifest["counts"]["by_kind"]
    assert by_kind.get("document") == 1 and by_kind.get("audio") == 1
    audio = next(f for f in manifest["files"] if f["kind"] == "audio")
    assert "transcrib" in (audio.get("note") or "")
    doc = next(f for f in manifest["files"] if f["kind"] == "document")
    assert doc.get("text") or doc.get("note")  # extracted text OR a degrade note


def test__render_digest_contains_header_and_files(tmp_path: Path):
    _touch(tmp_path / "a.txt", "Project kickoff with Acme.", datetime(2020, 5, 3, 9, 0))
    w = parse_period("May 2020")
    digest = render_digest(collect_archive(tmp_path, w, do_caption=False))
    assert "# Time Capsule" in digest
    assert "By day" in digest
    assert "a.txt" in digest


# ── Orchestration entry points ────────────────────────────────────────────────

def test__run_collect_root_unreachable():
    res = run_collect(root="/definitely/not/a/real/mount/xyz", period="May 2020")
    assert res["ok"] is False
    assert res["reason"] == "root-unreachable"


def test__run_collect_writes_artifacts(tmp_path: Path, monkeypatch):
    _touch(tmp_path / "a.txt", "Kickoff with Acme on the OANDA agent.", datetime(2020, 5, 3, 9, 0))
    # Keep artifacts in a tmp dir and skip the corpus provenance copy.
    monkeypatch.setattr(tc, "_OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(tc, "resolve_corpus_dir", lambda: tmp_path / "corpus")

    res = run_collect(root=str(tmp_path), period="May 2020", do_caption=False)
    assert res["ok"] is True
    assert res["counts"]["analyzed"] == 1
    assert Path(res["manifest_path"]).exists()
    assert Path(res["digest_path"]).exists()
    # suggested_when_iso falls on the period's last day (2020-05-31).
    assert res["suggested_when_iso"].startswith("2020-05-31")


def test__run_write_dual_writes(tmp_path: Path, monkeypatch):
    captured = {}

    def _fake_append_entry(day_file, entry, *, source, synthesized=False):
        captured["entry"] = entry
        captured["source"] = source
        captured["synthesized"] = synthesized
        return 42, "doc-xyz"

    monkeypatch.setattr(tc, "resolve_corpus_dir", lambda: tmp_path / "corpus")
    monkeypatch.setattr(tc, "append_entry", _fake_append_entry)

    synthesis = tmp_path / "s.synthesis.json"
    synthesis.write_text(json.dumps({
        "moment": "Shipped the OANDA forex agent",
        "what_happened": "Built and deployed the agent across May.",
        "why_it_stayed": "First fully-autonomous trade loop.",
        "possible_use": "portfolio",
        "tags": ["oanda", "agent"],
        "references": ["/data/a.txt", "/data/b.log"],
        "when_iso": "2020-05-31T00:00:00",
    }), encoding="utf-8")

    res = run_write(synthesis_path=str(synthesis))
    assert res["ok"] is True
    assert res["doc_id"] == "doc-xyz"
    assert res["references"] == 2
    assert captured["source"] == "time-capsule"
    assert captured["synthesized"] is True
    assert captured["entry"].moment == "Shipped the OANDA forex agent"
    assert captured["entry"].tags == ("oanda", "agent")


def test__run_write_empty_moment_is_noop(tmp_path: Path):
    synthesis = tmp_path / "s.json"
    synthesis.write_text(json.dumps({"moment": "   "}), encoding="utf-8")
    res = run_write(synthesis_path=str(synthesis))
    assert res["ok"] is False
    assert res["reason"] == "empty-moment"
    assert res["entries_written"] == 0
