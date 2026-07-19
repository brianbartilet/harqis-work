from datetime import datetime

import pytest

import workflows.hfl.tasks.ingest_looki as il
from apps.looki.references.dto.moment import DtoLookiMoment


class _FakeAdapter:
    def __init__(self, moments=(), ready=True):
        self._moments = list(moments)
        self._ready = ready
        self.called = False

    @property
    def status(self):
        return {"ready": self._ready, "backend": "looki-open-api" if self._ready else None}

    def list_moments(self, since, until, max_moments):
        self.called = True
        return list(self._moments)[:max_moments]


def _moment(moment_id: str | None = "moment-1", **kwargs):
    values = {
        "id": moment_id,
        "title": "Lunch with the team",
        "generated_text": (
            "Looki says we discussed the launch over lunch. "
            "https://signed.example/media?signature=secret"
        ),
        "started_at": "2026-07-18T12:30:00+08:00",
        "location_label": "Tanjong Pagar",
        "timezone": "+08:00",
        "tags": ("food", "team"),
    }
    values.update(kwargs)
    return DtoLookiMoment(**values)


@pytest.mark.smoke
def test_no_api_key_is_clean_noop_without_network(monkeypatch):
    fake = _FakeAdapter(ready=False)
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)

    result = il.ingest_looki_activity()

    assert result["entries_written"] == 0
    assert result["skipped"] == "no api key"
    assert fake.called is False


@pytest.mark.smoke
def test_no_moments_is_clean_noop(monkeypatch):
    fake = _FakeAdapter(ready=True)
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)

    result = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))

    assert result["entries_written"] == 0
    assert result["skipped"] == "no moments"
    assert fake.called is True


@pytest.mark.smoke
def test_writes_metadata_only_entry_with_stable_provenance(monkeypatch, tmp_path):
    fake = _FakeAdapter([_moment()])
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(il, "resolve_corpus_dir", lambda: tmp_path)
    indexed = []
    monkeypatch.setattr(
        il,
        "index_hfl_entry",
        lambda entry, *, source, synthesized=False, doc_id=None:
            indexed.append((entry, source, synthesized, doc_id)) or doc_id,
    )

    result = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))

    assert result["entries_written"] == 1
    assert result["duplicates_skipped"] == 0
    assert len(indexed) == 1
    entry, source, synthesized, doc_id = indexed[0]
    assert source == "looki"
    assert synthesized is False
    assert doc_id == il._looki_doc_id("moment-1")
    assert entry.references == ("looki:moment-1",)
    assert "unverified" in entry.what_happened.lower()
    assert "verify" in entry.why_it_stayed.lower()
    assert "looki" in entry.tags
    assert "wearable" in entry.tags

    text = (tmp_path / "2026-07-18.md").read_text(encoding="utf-8")
    assert "looki:moment-1" in text
    assert "temporary_url" not in text
    assert "signed.example" not in text

    retry = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 30))
    assert retry["entries_written"] == 0
    assert retry["duplicates_skipped"] == 1
    assert len(indexed) == 2  # deterministic ES upsert repairs transient failures
    assert (tmp_path / "2026-07-18.md").read_text().count("looki:moment-1") == 1


@pytest.mark.smoke
def test_existing_reference_prevents_duplicate_corpus_and_repairs_es(monkeypatch, tmp_path):
    day = tmp_path / "2026-07-17.md"
    complete = il._entry_for(_moment(), fallback=datetime(2026, 7, 17, 12, 0))
    day.write_text(complete.to_markdown() + "---\n\n", encoding="utf-8")
    fake = _FakeAdapter([_moment()])
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(il, "resolve_corpus_dir", lambda: tmp_path)
    indexed = []
    monkeypatch.setattr(il, "index_hfl_entry", lambda *args, **kwargs: indexed.append(kwargs))

    result = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))

    assert result["entries_written"] == 0
    assert result["duplicates_skipped"] == 1
    assert indexed == [{
        "source": "looki",
        "synthesized": False,
        "doc_id": il._looki_doc_id("moment-1"),
    }]
    assert day.read_text(encoding="utf-8").count("looki:moment-1") == 1


def test_reference_match_is_exact_and_global(monkeypatch, tmp_path):
    old_day = tmp_path / "2026-07-17.md"
    old_day.write_text("References:\n- looki:moment-10\n", encoding="utf-8")
    fake = _FakeAdapter([_moment(moment_id="moment-1")])
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(il, "resolve_corpus_dir", lambda: tmp_path)
    monkeypatch.setattr(il, "index_hfl_entry", lambda *args, **kwargs: None)

    result = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))

    assert result["entries_written"] == 1
    assert "looki:moment-1" in (tmp_path / "2026-07-18.md").read_text()


def test_claim_is_atomic_and_completion_persists(tmp_path):
    first = il._acquire_looki_claim(tmp_path, "moment-1")
    assert first is not None
    assert il._acquire_looki_claim(tmp_path, "moment-1") is None

    il._finish_looki_claim(first, completed=True)

    assert il._acquire_looki_claim(tmp_path, "moment-1") is None


def test_exact_ids_cannot_collide_in_es_identity():
    assert il._looki_doc_id("A.B") != il._looki_doc_id("a-b")
    assert il._looki_doc_id("x" * 100 + "1") != il._looki_doc_id("x" * 100 + "2")


def test_api_error_is_clean_retryable_noop(monkeypatch):
    class BrokenAdapter(_FakeAdapter):
        def list_moments(self, since, until, max_moments):
            raise TimeoutError("temporary outage")

    monkeypatch.setattr(il, "build_adapter", lambda _cfg: BrokenAdapter())

    result = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))

    assert result["entries_written"] == 0
    assert result["skipped"] == "api unavailable"


@pytest.mark.smoke
def test_missing_id_is_skipped(monkeypatch, tmp_path):
    fake = _FakeAdapter([_moment(moment_id=None)])
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(il, "resolve_corpus_dir", lambda: tmp_path)
    monkeypatch.setattr(il, "index_hfl_entry", lambda *args, **kwargs: pytest.fail("must not index"))

    result = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))

    assert result["entries_written"] == 0
    assert result["invalid_skipped"] == 1


@pytest.mark.parametrize(
    "text",
    [
        "See (https://signed.example/a?token=secret).",
        "See [source](https://signed.example/a?token=secret)",
        "source=https://signed.example/a?token=secret",
        "See <https://signed.example/a?token=secret>",
    ],
)
def test_safe_text_scrubs_wrapped_markdown_and_assigned_urls(text):
    safe = il._safe_text(text, 500)

    assert "signed.example" not in safe
    assert "https://" not in safe
    assert "[external-url-omitted]" in safe


def test_precise_coordinates_do_not_enter_durable_entry_but_place_names_do():
    moment = _moment(
        generated_text="Met there at 103.8198, 1.3521 before lunch",
        location_label="Tanjong Pagar",
        tags=("team", "103°49′11″E 1°21′08″N"),
    )

    entry = il._entry_for(moment, fallback=datetime(2026, 7, 19, 12, 0))
    markdown = entry.to_markdown()

    assert "1.3521" not in markdown
    assert "103.8198" not in markdown
    assert "103°49" not in markdown
    assert "Tanjong Pagar" in markdown
    assert "team" in entry.tags


@pytest.mark.parametrize("moment_id", ["bad\nid", "bad\rid", "bad\tid"])
def test_control_character_id_is_skipped_without_reference_or_identity(
    monkeypatch, tmp_path, moment_id
):
    fake = _FakeAdapter([_moment(moment_id=moment_id)])
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(il, "resolve_corpus_dir", lambda: tmp_path)
    monkeypatch.setattr(
        il,
        "index_hfl_entry",
        lambda *args, **kwargs: pytest.fail("invalid source IDs must not be indexed"),
    )

    result = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))

    assert result["entries_written"] == 0
    assert result["invalid_skipped"] == 1
    assert list(tmp_path.glob("*.md")) == []


def test_partial_reference_is_retryable_until_complete_terminated_entry(
    monkeypatch, tmp_path
):
    day = tmp_path / "2026-07-18.md"
    day.write_text(
        "## 2026-07-18 12:30\nReferences:\n                 - looki:moment-1\n",
        encoding="utf-8",
    )
    fake = _FakeAdapter([_moment()])
    monkeypatch.setattr(il, "build_adapter", lambda _cfg: fake)
    monkeypatch.setattr(il, "resolve_corpus_dir", lambda: tmp_path)
    monkeypatch.setattr(il, "index_hfl_entry", lambda *args, **kwargs: None)

    first_retry = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 25))
    second_retry = il.ingest_looki_activity(now=datetime(2026, 7, 19, 23, 30))
    text = day.read_text(encoding="utf-8")

    assert first_retry["entries_written"] == 1
    assert first_retry["duplicates_skipped"] == 0
    assert second_retry["entries_written"] == 0
    assert second_retry["duplicates_skipped"] == 1
    assert text.count("looki:moment-1") == 2  # partial fragment plus repaired entry
    assert text.rstrip().endswith("---")
