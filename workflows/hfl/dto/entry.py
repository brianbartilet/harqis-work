"""
workflows/hfl/dto/entry.py

`HflEntry` — the formal DTO for one Homework-for-Life corpus entry.

On-disk shape (Markdown; `## ` headers split entries — see
workflows/hfl/tasks/retrieve.py::_entries_for_file):

    ## YYYY-MM-DD HH:MM
    Moment:          <one-line headline>
    What happened:   <2-4 lines>
    Why it stayed:   <why this is story-worthy>
    Possible use:    <linkedin idea / retro / mentoring / lesson / etc.>
    Tags:            #tag1 #tag2 ...
    References:                       (← only rendered when non-empty)
                     - https://example.com/source
                     - C:\\host\\path\\file.md

`to_markdown()` is the single source of truth for the format; capture.py's
`_render_entry` delegates here so every producer emits an identical shape.
`from_markdown()` is its lossless inverse — `summarize` uses it to recover
an entry's `references` for the resolver, and it round-trips every field.

Backward compatibility is a hard requirement: with no references the
output is BYTE-IDENTICAL to the pre-DTO format, and parsing a legacy
entry (no `References:` line) yields `references == ()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

# Value column the original format aligned on ("Moment:" + 10 spaces = 17).
# ljust(_COL) reproduces every legacy label string exactly.
_COL = 17

# label text (before ':') → DTO field name, for from_markdown().
_LABELS = {
    "Moment": "moment",
    "What happened": "what_happened",
    "Why it stayed": "why_it_stayed",
    "Possible use": "possible_use",
    "Tags": "tags",
    "References": "references",
    "Source": "source",
    "Machine": "machine",
    "Entry ID": "entry_id",
}


def _norm_tags(tags: Optional[Iterable[str]]) -> tuple[str, ...]:
    if not tags:
        return ()
    return tuple(
        t.strip().lstrip("#") for t in tags if t and str(t).strip()
    )


def _norm_refs(refs: Optional[Iterable[str]]) -> tuple[str, ...]:
    if not refs:
        return ()
    return tuple(str(r).strip() for r in refs if r and str(r).strip())


@dataclass(frozen=True)
class HflEntry:
    """One HFL corpus entry. Immutable; render/parse via the two methods."""

    when: Optional[datetime]
    moment: str = ""
    what_happened: str = ""
    why_it_stayed: str = ""
    possible_use: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""
    machine: str = ""
    entry_id: str = ""

    def __post_init__(self) -> None:
        # Normalise without mutating (frozen): re-set via object.__setattr__.
        object.__setattr__(self, "moment", (self.moment or "").strip())
        object.__setattr__(self, "what_happened", (self.what_happened or "").strip())
        object.__setattr__(self, "why_it_stayed", (self.why_it_stayed or "").strip())
        object.__setattr__(self, "possible_use", (self.possible_use or "").strip())
        object.__setattr__(self, "tags", _norm_tags(self.tags))
        object.__setattr__(self, "references", _norm_refs(self.references))
        object.__setattr__(self, "source", (self.source or "").strip())
        object.__setattr__(self, "machine", (self.machine or "").strip())
        object.__setattr__(self, "entry_id", (self.entry_id or "").strip())

    # ── render ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_tags(tags: tuple[str, ...]) -> str:
        return " ".join(f"#{t}" for t in tags)

    def to_markdown(self) -> str:
        """Render the entry block (trailing blank line included).

        With empty `references` this is byte-identical to the legacy
        `_render_entry` output — existing producers are unaffected.
        """
        ts = self.when.strftime("%Y-%m-%d %H:%M") if self.when else ""
        lines = [f"## {ts}"]
        if self.source:
            lines.append(f"{'Source:'.ljust(_COL)}{self.source}")
        if self.machine:
            lines.append(f"{'Machine:'.ljust(_COL)}{self.machine}")
        if self.entry_id:
            lines.append(f"{'Entry ID:'.ljust(_COL)}{self.entry_id}")
        lines.extend([
            f"{'Moment:'.ljust(_COL)}{self.moment}",
            f"{'What happened:'.ljust(_COL)}{self.what_happened}",
            f"{'Why it stayed:'.ljust(_COL)}{self.why_it_stayed}",
            f"{'Possible use:'.ljust(_COL)}{self.possible_use}",
            f"{'Tags:'.ljust(_COL)}{self._fmt_tags(self.tags)}",
        ])
        if self.references:
            lines.append("References:")
            for r in self.references:
                lines.append(f"{' ' * _COL}- {r}")
        return "\n".join(lines) + "\n\n"

    # ── parse ─────────────────────────────────────────────────────────────────

    @classmethod
    def from_markdown(cls, header: str, body: str) -> "HflEntry":
        """Inverse of to_markdown().

        `header` is the `## ` line WITHOUT the leading `## ` (matches
        retrieve._entries_for_file's `entry["header"]`). `body` is
        everything after it. Tolerant: an unparseable timestamp yields
        `when=None`; a legacy body with no `References:` line yields
        `references=()`.
        """
        when: Optional[datetime] = None
        h = (header or "").strip()
        if h.startswith("## "):
            h = h[3:].strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                when = datetime.strptime(h, fmt)
                break
            except ValueError:
                continue

        vals: dict[str, str] = {}
        refs: list[str] = []
        collecting_refs = False
        for raw in (body or "").splitlines():
            stripped = raw.strip()
            if collecting_refs:
                if stripped.startswith("- "):
                    refs.append(stripped[2:].strip())
                    continue
                if not stripped:
                    continue
                collecting_refs = False  # fall through to key parsing
            if ":" not in raw:
                continue
            key = raw.split(":", 1)[0].strip()
            field_name = _LABELS.get(key)
            if field_name is None:
                continue
            if field_name == "references":
                collecting_refs = True
                continue
            vals[field_name] = raw.split(":", 1)[1].strip()

        tags = tuple(
            t.lstrip("#") for t in vals.get("tags", "").split() if t.strip()
        )
        return cls(
            when=when,
            moment=vals.get("moment", ""),
            what_happened=vals.get("what_happened", ""),
            why_it_stayed=vals.get("why_it_stayed", ""),
            possible_use=vals.get("possible_use", ""),
            tags=tags,
            references=tuple(r for r in refs if r),
            source=vals.get("source", ""),
            machine=vals.get("machine", ""),
            entry_id=vals.get("entry_id", ""),
        )
