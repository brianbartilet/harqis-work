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

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

# Value column the original format aligned on ("Moment:" + 10 spaces = 17).
# ljust(_COL) reproduces every legacy label string exactly.
_COL = 17
_VISIBLE_H1_H2 = re.compile(r"^( {0,3})#{1,2}(?=\s)")
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

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
    "Synthesized": "synthesized",
}


def _norm_tags(tags: Optional[Iterable[str]]) -> tuple[str, ...]:
    if not tags:
        return ()
    return tuple(
        t.strip().lstrip("#") for t in tags if t and str(t).strip()
    )


def canonicalize_tags(tags: Optional[Iterable[str]]) -> tuple[str, ...]:
    """Return deterministic lowercase Markdown-safe tag slugs."""
    canonical: set[str] = set()
    for tag in tags or ():
        ascii_tag = unicodedata.normalize("NFKD", str(tag)).encode(
            "ascii", "ignore"
        ).decode("ascii").casefold().lstrip("#")
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_tag).strip("-")
        if slug:
            canonical.add(slug)
    return tuple(sorted(canonical))


def _norm_refs(refs: Optional[Iterable[str]]) -> tuple[str, ...]:
    if not refs:
        return ()
    normalized = (str(reference).strip() for reference in refs if reference)
    return tuple(
        reference
        for reference in normalized
        if reference and not reference.casefold().startswith("http://")
    )


def _demote_visible_entry_headings(value: str) -> str:
    """Keep narrative Markdown below the canonical H2 entry boundary."""
    lines: list[str] = []
    fence_char = ""
    fence_length = 0
    for line in (value or "").splitlines():
        if fence_char:
            stripped = line.lstrip(" ") if len(line) - len(line.lstrip(" ")) <= 3 else line
            if re.fullmatch(
                rf"{re.escape(fence_char)}{{{fence_length},}}[ \t]*", stripped
            ):
                fence_char, fence_length = "", 0
            lines.append(line)
            continue
        opener = _FENCE_OPEN.match(line)
        if opener and opener.group(1).startswith("`") and "`" in opener.group(2):
            opener = None
        if opener:
            marker = opener.group(1)
            fence_char, fence_length = marker[0], len(marker)
            lines.append(line)
            continue
        line = _VISIBLE_H1_H2.sub(r"\1###", line)
        lines.append(line)
    return "\n".join(lines)


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
    synthesized: bool | None = None

    def __post_init__(self) -> None:
        # Normalise without mutating (frozen): re-set via object.__setattr__.
        for field_name in (
            "moment", "what_happened", "why_it_stayed", "possible_use"
        ):
            normalized = _demote_visible_entry_headings(
                (getattr(self, field_name) or "").strip()
            )
            object.__setattr__(self, field_name, normalized)
        object.__setattr__(self, "tags", _norm_tags(self.tags))
        object.__setattr__(self, "references", _norm_refs(self.references))
        object.__setattr__(self, "source", (self.source or "").strip())
        object.__setattr__(self, "machine", (self.machine or "").strip())
        object.__setattr__(self, "entry_id", (self.entry_id or "").strip())

    # ── render ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_tags(tags: tuple[str, ...]) -> str:
        return " ".join(f"#{t}" for t in tags)

    @staticmethod
    def _fmt_field(label: str, value: str) -> str:
        prefix = f"{label}:".ljust(_COL)
        if "\n" in value or value.lstrip().startswith("#"):
            return f"{prefix}\n{value}"
        return f"{prefix}{value}"

    def to_markdown(self) -> str:
        """Render the entry block (trailing blank line included).

        With empty `references` this is byte-identical to the legacy
        `_render_entry` output — existing producers are unaffected.
        """
        if self.when:
            ts = self.when.strftime("%Y-%m-%d %H:%M")
            if self.when.second or self.when.microsecond:
                ts = self.when.strftime("%Y-%m-%d %H:%M:%S")
                if self.when.microsecond:
                    fraction = f"{self.when.microsecond:06d}".rstrip("0")
                    ts += f".{fraction.ljust(3, '0')}"
        else:
            ts = ""
        lines = [f"## {ts}"]
        if self.source:
            lines.append(f"{'Source:'.ljust(_COL)}{self.source}")
        if self.machine:
            lines.append(f"{'Machine:'.ljust(_COL)}{self.machine}")
        if self.entry_id:
            lines.append(f"{'Entry ID:'.ljust(_COL)}{self.entry_id}")
        if self.synthesized is not None:
            value = "true" if self.synthesized else "false"
            lines.append(f"{'Synthesized:'.ljust(_COL)}{value}")
        lines.extend([
            self._fmt_field("Moment", self.moment),
            self._fmt_field("What happened", self.what_happened),
            self._fmt_field("Why it stayed", self.why_it_stayed),
            self._fmt_field("Possible use", self.possible_use),
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
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                when = datetime.strptime(h, fmt)
                break
            except ValueError:
                continue

        vals: dict[str, str] = {}
        refs: list[str] = []
        collecting_refs = False
        current_field: str | None = None
        for raw in (body or "").splitlines():
            stripped = raw.strip()
            if collecting_refs:
                if stripped.startswith("- "):
                    refs.append(stripped[2:].strip())
                    continue
                if not stripped:
                    continue
                collecting_refs = False
            key = raw.split(":", 1)[0].strip() if ":" in raw else ""
            field_name = _LABELS.get(key)
            if field_name:
                if field_name == "source" and current_field and current_field != "source":
                    vals[current_field] = f"{vals.get(current_field, '')}\n{raw.rstrip()}"
                    continue
                current_field = field_name
                if field_name == "references":
                    collecting_refs = True
                    continue
                vals[field_name] = raw.split(":", 1)[1].strip()
            elif current_field and current_field != "references":
                vals[current_field] = f"{vals.get(current_field, '')}\n{raw.rstrip()}"

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
            synthesized=(
                vals.get("synthesized", "").casefold() == "true"
                if vals.get("synthesized", "").casefold() in {"true", "false"}
                else None
            ),
        )
