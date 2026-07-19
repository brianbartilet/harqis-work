"""Tests for workflows/hfl/tasks/ingest_plaud.py.

Covers the no-op contracts (no backend / no recordings → no write, no LLM),
the raw-fallback distiller (no API), the one-entry-per-recording dual-write
contract (index_hfl_entry monkeypatched), and the per-recording deterministic
doc id. The full live pipeline (real Plaud + Whisper + Anthropic + scp) is
manual-only.
"""
import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length, is_in

import workflows.hfl.tasks.ingest_plaud as ip
from apps.plaud.references.dto.recording import DtoPlaudRecording


class _FakeAdapter:
    def __init__(self, recordings, active="folder"):
        self._recs = recordings
        self._active = active
        self.list_called = False

    @property
    def status(self):
        return {"active": self._active}

    def list_recordings(self, since=None, until=None):
        self.list_called = True
        return list(self._recs)

    def ensure_audio_local(self, rec, dest_dir):
        return rec.audio_path


def _rec(**kw):
    base = dict(id="rec1", title="Standup", started_at="2026-06-09T09:00:00",
                origin="folder")
    base.update(kw)
    return DtoPlaudRecording(**base)


# ── no-op contracts ───────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_no_backend_is_clean_noop(monkeypatch):
    fake = _FakeAdapter([], active=None)
    monkeypatch.setattr(ip, "build_adapter", lambda _cfg: fake)
    result = ip.ingest_plaud_activity()
    assert_that(result["entries_written"], equal_to(0))
    assert_that(result["skipped"], equal_to("no backend"))
    assert_that(fake.list_called, equal_to(False))  # no network when no backend


@pytest.mark.smoke
def test_no_recordings_is_clean_noop(monkeypatch):
    fake = _FakeAdapter([], active="folder")
    monkeypatch.setattr(ip, "build_adapter", lambda _cfg: fake)
    result = ip.ingest_plaud_activity()
    assert_that(result["entries_written"], equal_to(0))
    assert_that(result["skipped"], equal_to("no recordings"))


# ── distiller raw fallback (no API) ───────────────────────────────────────────

@pytest.mark.smoke
def test_distill_raw_fallback_no_api():
    rec = _rec(transcript="we shipped the thing")
    d = ip.distill_plaud_recording(rec, "we shipped the thing", synthesize=False)
    assert_that(d["skip"], equal_to(False))
    assert_that(d["synthesized"], equal_to(False))
    assert_that("voice", is_in(d["tags"]))
    assert_that("plaud", is_in(d["tags"]))


# ── one entry per recording + dual-write + deterministic doc id ───────────────

@pytest.mark.smoke
def test_writes_one_entry_per_recording(monkeypatch, tmp_path):
    recs = [
        _rec(id="aaa", title="Standup", transcript="planned the migration"),
        _rec(id="bbb", title="Call with vendor", transcript="negotiated pricing"),
    ]
    fake = _FakeAdapter(recs, active="folder")
    monkeypatch.setattr(ip, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(ip, "distill_plaud_recording",
                        lambda rec, t, **kw: {"skip": False, "moment": f"M:{rec.id}",
                                              "what_happened": "x", "why_it_stayed": "y",
                                              "possible_use": "voice-note",
                                              "tags": ["alpha"], "synthesized": False})
    submitted = []
    monkeypatch.setattr(
        ip,
        "submit_hfl_entry",
        lambda entry, *, source, synthesized=False, dedup_key=None, es_doc_id=None:
        submitted.append((source, es_doc_id, entry.moment, dedup_key)) or {
            "delivery": "forwarded", "path": "", "doc_id": es_doc_id,
        },
    )

    result = ip.ingest_plaud_activity(archive=False, allow_whisper=False)

    assert_that(result["entries_written"], equal_to(2))
    assert_that(submitted, has_length(2))
    # source tag + deterministic per-recording doc id
    assert_that(submitted[0][0], equal_to("plaud"))
    assert_that(submitted[0][1], equal_to("20260609-plaud-aaa"))
    assert_that(submitted[1][1], equal_to("20260609-plaud-bbb"))
    assert_that(submitted[0][2], equal_to("M:aaa"))
    assert_that(submitted[0][3], equal_to("plaud:aaa"))


@pytest.mark.smoke
def test_recording_with_summary_no_transcript_still_ingests(monkeypatch, tmp_path):
    # No transcript, Whisper disabled, but Plaud summary present → still an entry.
    recs = [_rec(id="ccc", transcript=None, summary="vendor agreed to net-30")]
    fake = _FakeAdapter(recs, active="folder")
    monkeypatch.setattr(ip, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(
        ip,
        "submit_hfl_entry",
        lambda entry, **kwargs: {"delivery": "forwarded", "path": ""},
    )

    result = ip.ingest_plaud_activity(archive=False, allow_whisper=False)
    assert_that(result["entries_written"], equal_to(1))


@pytest.mark.smoke
def test_archive_day_uses_local_copy_for_localhost(monkeypatch, tmp_path):
    archive_base = tmp_path / "archive"
    staging_dir = tmp_path / "2026-06-24"
    staging_dir.mkdir()
    (staging_dir / "2026-06-24-summary.md").write_text("ok", encoding="utf-8")
    monkeypatch.setenv("PLAUD_ARCHIVE_HOST", "localhost")
    monkeypatch.setenv("PLAUD_ARCHIVE_PATH", str(archive_base))

    result = ip._archive_day(staging_dir, "2026-06-24")

    assert_that(result["archived"], equal_to(True))
    assert_that(result["mode"], equal_to("local-copy"))
    assert_that((archive_base / "2026-06-24" / "2026-06-24-summary.md").exists(), equal_to(True))


@pytest.mark.skip(reason="Manual only — live Plaud + Whisper + Anthropic + scp archive")
def test_full_pipeline_live():
    ip.ingest_plaud_activity()
