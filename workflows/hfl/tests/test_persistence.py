from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from workflows.hfl.dto import HflEntry
from workflows.hfl import persistence


def _entry(moment: str = "A durable moment") -> HflEntry:
    return HflEntry(
        when=datetime(2026, 7, 19, 9, 30),
        moment=moment,
        what_happened="Something worth keeping happened.",
        why_it_stayed="It may be useful again.",
        possible_use="Retrospective",
        tags=("hfl", "durability"),
        references=("https://example.com/source",),
    )


def test_envelope_is_deterministic_and_round_trips():
    first = persistence.make_envelope(
        _entry(), source="capture", machine="windows-work-all"
    )
    second = persistence.make_envelope(
        _entry(), source="capture", machine="windows-work-all"
    )

    restored = persistence.EntryEnvelope.from_payload(first.to_payload())

    assert first.entry.entry_id == second.entry.entry_id
    assert restored == first
    assert restored.entry.source == "capture"
    assert restored.entry.machine == "windows-work-all"


def test_persist_is_locked_and_idempotent(tmp_path, monkeypatch):
    indexed = []
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: indexed.append((entry, kwargs)) or kwargs["doc_id"],
    )
    envelope = persistence.make_envelope(
        _entry(), source="capture", machine="windows-work-all"
    )

    first = persistence.persist_envelope(envelope, corpus_dir=tmp_path)
    second = persistence.persist_envelope(envelope, corpus_dir=tmp_path)
    text = (tmp_path / "2026-07-19.md").read_text(encoding="utf-8")

    assert first["duplicate"] is False
    assert first["bytes_written"] > 0
    assert second["duplicate"] is True
    assert second["bytes_written"] == 0
    assert text.count(envelope.entry.entry_id) == 1
    assert len(indexed) == 2  # the ES projection is safely upserted on replay


def test_persist_prepends_new_entry_to_daily_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: kwargs["doc_id"],
    )
    older = persistence.make_envelope(
        _entry("Older moment"), source="capture", machine="windows-work-all"
    )
    newer = persistence.make_envelope(
        replace(_entry("Newer moment"), when=datetime(2026, 7, 19, 10, 45)),
        source="capture",
        machine="windows-work-all",
    )

    persistence.persist_envelope(older, corpus_dir=tmp_path)
    persistence.persist_envelope(newer, corpus_dir=tmp_path)

    text = (tmp_path / "2026-07-19.md").read_text(encoding="utf-8")
    assert text.startswith(newer.entry.to_markdown())
    assert text.index("Newer moment") < text.index("Older moment")


def test_submit_retains_outbox_when_broker_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "outbox_dir", lambda: tmp_path)
    monkeypatch.setattr(persistence, "is_canonical_machine", lambda machine=None: False)
    monkeypatch.setattr(
        persistence,
        "_dispatch",
        lambda envelope: (_ for _ in ()).throw(ConnectionError("broker down")),
    )

    result = persistence.submit_hfl_entry(_entry(), source="capture")

    assert result["delivery"] == "outbox"
    assert result["error"] == "ConnectionError"
    assert len(tuple(tmp_path.glob("*.json"))) == 1


def test_flush_forwards_and_removes_outbox_after_broker_acceptance(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "outbox_dir", lambda: tmp_path)
    monkeypatch.setattr(persistence, "is_canonical_machine", lambda machine=None: False)
    envelope = persistence.make_envelope(
        _entry(), source="capture", machine="windows-work-all"
    )
    persistence.save_to_outbox(envelope)
    dispatched = []
    monkeypatch.setattr(
        persistence,
        "_dispatch",
        lambda item: dispatched.append(item.entry.entry_id) or "task-id",
    )

    result = persistence.flush_outbox()

    assert result == {"found": 1, "delivered": 1, "failed": 0, "invalid": 0}
    assert dispatched == [envelope.entry.entry_id]
    assert not tuple(tmp_path.glob("*.json"))
