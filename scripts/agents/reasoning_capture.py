#!/usr/bin/env python3
"""
reasoning_capture.py — Log task reasoning and decisions to HFL corpus.

Captures structured reasoning entries to the HFL corpus with optional tags and
references, enabling pattern detection across agent decisions.

Usage:
    python reasoning_capture.py \
        --task "Task name" \
        --decision "Why this approach" \
        --outcome "What happened" \
        --tags "tag1,tag2" \
        --refs "ref1.md,ref2.md"

Entry format is backward compatible with existing HflEntry DTO.
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Minimal HflEntry implementation (self-contained, no external deps)
# ─────────────────────────────────────────────────────────────────────────────

_COL = 17  # Value column alignment (legacy format)


def _norm_tags(tags: Optional[Iterable[str]]) -> tuple[str, ...]:
    """Normalize tags: strip whitespace and leading #."""
    if not tags:
        return ()
    return tuple(
        t.strip().lstrip("#") for t in tags if t and str(t).strip()
    )


def _norm_refs(refs: Optional[Iterable[str]]) -> tuple[str, ...]:
    """Normalize references: strip whitespace."""
    if not refs:
        return ()
    return tuple(str(r).strip() for r in refs if r and str(r).strip())


@dataclass(frozen=True)
class HflEntry:
    """Minimal HFL entry DTO — matches workflows/hfl/dto/entry.py."""
    
    when: Optional[datetime]
    moment: str = ""
    what_happened: str = ""
    why_it_stayed: str = ""
    possible_use: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize fields (frozen dataclass)."""
        object.__setattr__(self, "moment", (self.moment or "").strip())
        object.__setattr__(self, "what_happened", (self.what_happened or "").strip())
        object.__setattr__(self, "why_it_stayed", (self.why_it_stayed or "").strip())
        object.__setattr__(self, "possible_use", (self.possible_use or "").strip())
        object.__setattr__(self, "tags", _norm_tags(self.tags))
        object.__setattr__(self, "references", _norm_refs(self.references))

    @staticmethod
    def _fmt_tags(tags: tuple[str, ...]) -> str:
        """Format tags for markdown output."""
        return " ".join(f"#{t}" for t in tags)

    def to_markdown(self) -> str:
        """Render entry block (backward compatible with legacy format)."""
        ts = self.when.strftime("%Y-%m-%d %H:%M") if self.when else ""
        lines = [
            f"## {ts}",
            f"{'Moment:'.ljust(_COL)}{self.moment}",
            f"{'What happened:'.ljust(_COL)}{self.what_happened}",
            f"{'Why it stayed:'.ljust(_COL)}{self.why_it_stayed}",
            f"{'Possible use:'.ljust(_COL)}{self.possible_use}",
            f"{'Tags:'.ljust(_COL)}{self._fmt_tags(self.tags)}",
        ]
        if self.references:
            lines.append("References:")
            for r in self.references:
                lines.append(f"{' ' * _COL}- {r}")
        return "\n".join(lines) + "\n\n"

    @classmethod
    def from_markdown(cls, header: str, body: str) -> "HflEntry":
        """Parse entry from markdown (inverse of to_markdown)."""
        when: Optional[datetime] = None
        h = (header or "").strip()
        if h.startswith("## "):
            h = h[3:].strip()
        
        # Try parsing timestamp
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                when = datetime.strptime(h, fmt)
                break
            except ValueError:
                continue

        # Parse fields
        labels = {
            "Moment": "moment",
            "What happened": "what_happened",
            "Why it stayed": "why_it_stayed",
            "Possible use": "possible_use",
            "Tags": "tags",
            "References": "references",
        }
        
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
                collecting_refs = False
            if ":" not in raw:
                continue
            key = raw.split(":", 1)[0].strip()
            field_name = labels.get(key)
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
        )


# ─────────────────────────────────────────────────────────────────────────────
# Corpus path resolution (matches harqis-work behavior)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_corpus_dir() -> Path:
    """
    Resolve HFL corpus directory using documented precedence:
    1. HFL_CORPUS_PATH env var
    2. Default to ~/GIT/harqis-work/logs/hfl
    """
    env_path = os.environ.get("HFL_CORPUS_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()
    
    # Default fallback
    default = Path.home() / "GIT" / "harqis-work" / "logs" / "hfl"
    return default.resolve()


# ─────────────────────────────────────────────────────────────────────────────
# Main capture function
# ─────────────────────────────────────────────────────────────────────────────

def capture_reasoning(
    task: str,
    decision: str,
    outcome: str,
    tags: list[str] | None = None,
    refs: list[str] | None = None,
) -> HflEntry:
    """
    Log a reasoning entry to the HFL corpus.
    
    Args:
        task: Task name (becomes 'moment')
        decision: Decision logic / reasoning (what_happened)
        outcome: Result or insight (why_it_stayed)
        tags: List of tags (e.g., ['reasoning', 'pattern-detected'])
        refs: List of file paths or URLs for context
    
    Returns:
        The created HflEntry
    """
    when = datetime.now()
    
    # Build entry
    entry = HflEntry(
        when=when,
        moment=task,
        what_happened=decision,
        why_it_stayed=outcome,
        possible_use="Agent learning: apply pattern to similar tasks",
        tags=tuple(tags or []),
        references=tuple(refs or []),
    )
    
    # Resolve corpus directory and ensure it exists
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    
    # Daily file
    day_file = corpus_dir / when.strftime("%Y-%m-%d.md")
    
    # Append entry
    with open(day_file, "a", encoding="utf-8") as f:
        f.write(entry.to_markdown())
    
    print(f"✓ Reasoning entry logged to {day_file}")
    return entry


# ─────────────────────────────────────────────────────────────────────────────
# CLI interface
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Log task reasoning and decisions to HFL corpus"
    )
    parser.add_argument("--task", required=True, help="Task name")
    parser.add_argument("--decision", required=True, help="Decision / reasoning logic")
    parser.add_argument("--outcome", required=True, help="Result or insight")
    parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags (e.g., 'reasoning,pattern-detected')",
    )
    parser.add_argument(
        "--refs",
        default="",
        help="Comma-separated references (file paths or URLs)",
    )
    
    args = parser.parse_args()
    
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    refs = [r.strip() for r in args.refs.split(",") if r.strip()]
    
    capture_reasoning(
        task=args.task,
        decision=args.decision,
        outcome=args.outcome,
        tags=tags,
        refs=refs,
    )
