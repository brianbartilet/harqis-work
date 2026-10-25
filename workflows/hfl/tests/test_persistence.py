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


def test_persist_envelope_holds_corpus_wide_lock(tmp_path, monkeypatch):
    from workflows.hfl import write_lock

    events = []

    class Lock:
        def __enter__(self):
            events.append("entered")

        def __exit__(self, *_args):
            events.append("exited")

    monkeypatch.setattr(
        write_lock, "corpus_write_lock",
        lambda root: (events.append(root) or Lock()),
    )

    def persist_locked(envelope, **kwargs):
        assert events[-1] == "entered"
        assert kwargs["corpus_dir"] == tmp_path.resolve()
        return {"entry_id": envelope.entry.entry_id}

    monkeypatch.setattr(persistence, "_persist_envelope_locked", persist_locked)
    envelope = persistence.make_envelope(
        _entry(), source="capture", machine="windows-work-all",
    )
    result = persistence.persist_envelope(envelope, corpus_dir=tmp_path)
    assert result == {"entry_id": envelope.entry.entry_id}
    assert events == [tmp_path.resolve(), "entered", "exited"]


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


def test_envelope_embeds_synthesized_provenance_in_canonical_entry():
    envelope = persistence.make_envelope(
        _entry(), source="desktop", machine="harqis-server", synthesized=True,
    )

    restored = persistence.EntryEnvelope.from_payload(envelope.to_payload())

    assert envelope.entry.synthesized is True
    assert restored.entry.synthesized is True
    assert "Synthesized:     true" in envelope.entry.to_markdown()


def test_envelope_round_trips_duplicate_replacement_policy():
    envelope = persistence.make_envelope(
        _entry(), source="facebook", machine="windows-work-all",
        dedup_key="facebook:friend:2026-07-13", replace_duplicate=True,
    )

    restored = persistence.EntryEnvelope.from_payload(envelope.to_payload())

    assert restored == envelope
    assert restored.replace_duplicate is True


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


def test_duplicate_replay_indexes_retained_markdown_not_new_model_text(tmp_path, monkeypatch):
    indexed = []
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: indexed.append((entry, kwargs)) or kwargs["doc_id"],
    )
    monkeypatch.setattr("workflows.hfl.entity_events.notify_change", lambda _: None)
    original = persistence.make_envelope(
        _entry("Original meeting"), source="granola", machine="canonical",
        dedup_key="granola:meeting", synthesized=True,
    )
    replay = persistence.make_envelope(
        replace(_entry("Edited meeting"), what_happened="Changed source text"),
        source="granola", machine="canonical", dedup_key="granola:meeting",
        synthesized=False,
    )
    persistence.persist_envelope(original, corpus_dir=tmp_path)
    result = persistence.persist_envelope(replay, corpus_dir=tmp_path)
    assert result["duplicate"]
    assert indexed[-1][0].moment == "Original meeting"
    assert indexed[-1][0].what_happened == original.entry.what_happened
    assert indexed[-1][1]["synthesized"] is True
    assert "Edited meeting" not in (tmp_path / "2026-07-19.md").read_text(encoding="utf-8")


def test_persist_orders_daily_markdown_by_timestamp_descending(tmp_path, monkeypatch):
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

    persistence.persist_envelope(newer, corpus_dir=tmp_path)
    persistence.persist_envelope(older, corpus_dir=tmp_path)

    text = (tmp_path / "2026-07-19.md").read_text(encoding="utf-8")
    assert text.startswith(newer.entry.to_markdown())
    assert text.index("Newer moment") < text.index("Older moment")


def test_persist_keeps_model_section_headings_inside_one_canonical_entry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: kwargs["doc_id"],
    )
    answer = replace(
        _entry("Sharing answer"),
        what_happened="Answer:\n\n## Work & Career\nDetails\n\n## Travel\nMore details",
    )
    envelope = persistence.make_envelope(
        answer, source="sharing-audit", machine="harqis-server"
    )

    persistence.persist_envelope(envelope, corpus_dir=tmp_path)
    persistence.persist_envelope(
        persistence.make_envelope(
            replace(_entry("Later entry"), when=datetime(2026, 7, 19, 10, 45)),
            source="capture",
            machine="harqis-server",
        ),
        corpus_dir=tmp_path,
    )

    text = (tmp_path / "2026-07-19.md").read_text(encoding="utf-8")
    parsed = tuple(persistence._entry_blocks(text))
    assert len(parsed) == 2
    assert "\n## Work & Career\n" not in text
    assert "\n### Work & Career\n" in text
    assert next(item for item in parsed if item.entry_id == envelope.entry.entry_id) == envelope.entry


def test_persist_inserts_backdated_entry_and_retains_document_preamble(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "workflows.hfl.es_store.index_hfl_entry",
        lambda entry, **kwargs: kwargs["doc_id"],
    )
    day_file = tmp_path / "2026-07-19.md"
    day_file.write_text(
        "# Daily notes\n\n"
        + replace(_entry("Latest"), when=datetime(2026, 7, 19, 12, 0)).to_markdown()
        + replace(_entry("Earliest"), when=datetime(2026, 7, 19, 8, 0)).to_markdown(),
        encoding="utf-8",
    )
    middle = persistence.make_envelope(
        replace(_entry("Middle"), when=datetime(2026, 7, 19, 10, 0)),
        source="capture",
        machine="windows-work-all",
    )

    persistence.persist_envelope(middle, corpus_dir=tmp_path)

    text = day_file.read_text(encoding="utf-8")
    assert text.startswith("# Daily notes\n\n")
    assert text.index("Latest") < text.index("Middle") < text.index("Earliest")


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
    monkeypatch.setenv('HFL_TIMELINE_STORE_PATH', str(tmp_path / 'unused.sqlite3'))
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


def test_audit_persistence_does_not_schedule_entity_identification(tmp_path, monkeypatch):
    from workflows.hfl import entity_events
    notified, indexed = [], []
    monkeypatch.setattr(entity_events, 'notify_change', lambda identity: notified.append(identity))
    monkeypatch.setattr('workflows.hfl.es_store.index_hfl_entry',
        lambda entry, **kwargs: indexed.append(entry) or kwargs['doc_id'])
    for source in ('entities-audit', 'entity-consolidation', 'notes'):
        envelope = persistence.make_envelope(_entry(source), source=source, machine='harqis-server')
        persistence.persist_envelope(envelope, corpus_dir=tmp_path)
        persistence.persist_envelope(envelope, corpus_dir=tmp_path)
        if source != 'notes':
            assert notified == []
    assert len(indexed) == 6
    assert len(notified) == 2
    assert 'entities-audit' in (tmp_path / '2026-07-19.md').read_text(encoding='utf-8')
