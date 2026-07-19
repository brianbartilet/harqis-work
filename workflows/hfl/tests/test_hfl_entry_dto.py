"""
Tests for workflows/hfl/dto/entry.py (HflEntry).

The hard guarantees: no-reference output is byte-identical to the
pre-DTO format, and to_markdown()↔from_markdown() round-trips every
field including references.
"""

from datetime import datetime

from workflows.hfl.dto import HflEntry
from workflows.hfl.tasks.capture import _render_entry


# ── Backward compatibility ────────────────────────────────────────────────────

def test__no_reference_output_is_byte_identical_to_legacy():
    when = datetime(2026, 5, 13, 9, 14)
    expected = (
        "## 2026-05-13 09:14\n"
        "Moment:          A small bug\n"
        "What happened:   Env var leaked into Path\n"
        "Why it stayed:   Small details, big problems\n"
        "Possible use:    lesson\n"
        "Tags:            #debugging #python\n\n"
    )
    got = _render_entry(
        when=when,
        moment="A small bug",
        what_happened="Env var leaked into Path",
        why_it_stayed="Small details, big problems",
        possible_use="lesson",
        tags=["debugging", "python"],
    )
    assert got == expected


def test__legacy_body_without_references_parses_to_empty_tuple():
    md = _render_entry(
        when=datetime(2026, 5, 13, 9, 14),
        moment="m", what_happened="w", why_it_stayed="y",
        possible_use="p", tags=["a"],
    )
    header, _, body = md.partition("\n")
    entry = HflEntry.from_markdown(header, body)
    assert entry.references == ()
    assert entry.tags == ("a",)
    assert entry.moment == "m"


# ── Round-trip ────────────────────────────────────────────────────────────────

def test__round_trip_with_references_incl_paths_with_spaces():
    entry = HflEntry(
        when=datetime(2026, 5, 17, 23, 0),
        moment="Wired the references field",
        what_happened="Added a DTO and a resolver.",
        why_it_stayed="Closes the provenance loop.",
        possible_use="portfolio",
        tags=("hfl", "dto"),
        references=(
            "https://github.com/owner/repo/commit/abc1234",
            r"C:\dump\2026-05-17\my screenshot.png",
        ),
    )
    md = entry.to_markdown()
    assert "References:" in md
    header, _, body = md.partition("\n")
    back = HflEntry.from_markdown(header, body)
    assert back.when == entry.when
    assert back.moment == entry.moment
    assert back.what_happened == entry.what_happened
    assert back.why_it_stayed == entry.why_it_stayed
    assert back.possible_use == entry.possible_use
    assert back.tags == entry.tags
    assert back.references == entry.references


def test__references_rendered_only_when_present():
    base = dict(
        when=datetime(2026, 5, 17, 23, 0), moment="m",
        what_happened="w", why_it_stayed="y", possible_use="p", tags=("t",),
    )
    assert "References:" not in HflEntry(**base).to_markdown()
    assert "References:" in HflEntry(**base, references=("x",)).to_markdown()


def test__from_markdown_tolerates_bad_timestamp():
    entry = HflEntry.from_markdown("not a date", "Moment:          hi\n")
    assert entry.when is None
    assert entry.moment == "hi"


def test_canonical_metadata_is_optional_and_round_trips():
    entry = HflEntry(
        when=datetime(2026, 7, 19, 9, 30),
        moment="Canonical entry",
        source="browsing",
        machine="windows-work-all",
        entry_id="hfl-abc123",
    )

    markdown = entry.to_markdown()
    header, body = markdown.split("\n", 1)
    restored = HflEntry.from_markdown(header, body)

    assert "Source:          browsing" in markdown
    assert "Machine:         windows-work-all" in markdown
    assert "Entry ID:        hfl-abc123" in markdown
    assert restored.source == entry.source
    assert restored.machine == entry.machine
    assert restored.entry_id == entry.entry_id


def test__normalisation_strips_and_dehashes():
    e = HflEntry(
        when=datetime(2026, 5, 17, 23, 0),
        moment="  spaced  ",
        tags=("#tag1", " tag2 ", ""),
        references=(" https://x ", "", "  /p/q  "),
    )
    assert e.moment == "spaced"
    assert e.tags == ("tag1", "tag2")
    assert e.references == ("https://x", "/p/q")
