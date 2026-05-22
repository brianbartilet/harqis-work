#!/usr/bin/env python3
"""
lessons_extractor.py — Weekly autonomous pattern detection from HFL reasoning.

Runs autonomously (typically Sundays 22:00 SGT via cron). Scans reasoning entries
from the past 7 days, detects recurring patterns, and writes insights to
~/.hermes/memory/agent_lessons.md.

Pattern detection logic:
  1. Group entries by tags (e.g., all #debugging, all #refactoring)
  2. Within each tag, identify common decision patterns
  3. Surface learnings that apply to future similar tasks
  4. Rank by frequency; deduplicate

No external dependencies — self-contained HFL parsing.
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Minimal HflEntry implementation (self-contained)
# ─────────────────────────────────────────────────────────────────────────────

_COL = 17


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
    """Minimal HFL entry DTO."""
    
    when: Optional[datetime]
    moment: str = ""
    what_happened: str = ""
    why_it_stayed: str = ""
    possible_use: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "moment", (self.moment or "").strip())
        object.__setattr__(self, "what_happened", (self.what_happened or "").strip())
        object.__setattr__(self, "why_it_stayed", (self.why_it_stayed or "").strip())
        object.__setattr__(self, "possible_use", (self.possible_use or "").strip())
        object.__setattr__(self, "tags", _norm_tags(self.tags))
        object.__setattr__(self, "references", _norm_refs(self.references))

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
# Corpus path resolution
# ─────────────────────────────────────────────────────────────────────────────

def resolve_corpus_dir() -> Path:
    """Resolve HFL corpus directory."""
    env_path = os.environ.get("HFL_CORPUS_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()
    
    # Default fallback
    return (Path.home() / "GIT" / "harqis-work" / "logs" / "hfl").resolve()


# ─────────────────────────────────────────────────────────────────────────────
# Pattern extraction logic
# ─────────────────────────────────────────────────────────────────────────────

def _parse_entries_from_text(text: str) -> list[HflEntry]:
    """Split text by ## headers and parse each entry."""
    entries = []
    current_header = None
    current_body = []
    
    for line in text.splitlines():
        if line.startswith("## "):
            # Save previous entry if exists
            if current_header is not None:
                body_text = "\n".join(current_body).rstrip()
                try:
                    entry = HflEntry.from_markdown(current_header, body_text)
                    entries.append(entry)
                except Exception:
                    pass
            # Start new entry
            current_header = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    
    # Save final entry
    if current_header is not None:
        body_text = "\n".join(current_body).rstrip()
        try:
            entry = HflEntry.from_markdown(current_header, body_text)
            entries.append(entry)
        except Exception:
            pass
    
    return entries


def extract_lessons_from_corpus(days_back: int = 7) -> dict[str, list[str]]:
    """
    Scan HFL corpus for reasoning entries in the past N days.
    Group by tags; extract patterns within each tag.
    
    Returns:
        dict[tag] -> list of lesson insights
    """
    corpus_dir = resolve_corpus_dir()
    if not corpus_dir.exists():
        return {}
    
    lessons_by_tag = defaultdict(list)
    
    # Scan past N days of corpus files
    cutoff = (datetime.now() - timedelta(days=days_back)).date()
    for corpus_file in sorted(corpus_dir.glob("*.md")):
        try:
            # Parse date from filename YYYY-MM-DD.md
            file_date = datetime.strptime(corpus_file.stem, "%Y-%m-%d").date()
            if file_date < cutoff:
                continue
        except ValueError:
            continue
        
        # Parse entries from file
        text = corpus_file.read_text(encoding="utf-8")
        entries = _parse_entries_from_text(text)
        
        # Group by tags
        for entry in entries:
            if not entry.tags:
                continue
            for tag in entry.tags:
                # Build a lesson key: tag + short outcome summary
                lesson_key = f"{tag}: {entry.why_it_stayed[:60]}"
                lessons_by_tag[tag].append(lesson_key)
    
    return lessons_by_tag


def deduplicate_and_rank(lessons_by_tag: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Within each tag, deduplicate lessons and rank by frequency.
    Returns top 3 per tag.
    """
    ranked = {}
    for tag, lessons in lessons_by_tag.items():
        # Count occurrences (case-insensitive)
        counts = defaultdict(int)
        for lesson in lessons:
            counts[lesson] += 1
        
        # Sort by count, take top 3
        top = sorted(counts.items(), key=lambda x: -x[1])[:3]
        ranked[tag] = [f"{lesson} (seen {count}x)" for lesson, count in top]
    
    return ranked


def write_lessons_to_memory(lessons: dict[str, list[str]]) -> Path:
    """
    Append extracted lessons to ~/.hermes/memory/agent_lessons.md.
    Format: timestamp + tag + lessons for future agent consultation.
    
    Returns:
        Path to the lessons file
    """
    memory_dir = Path.home() / ".hermes" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    
    lessons_file = memory_dir / "agent_lessons.md"
    
    # Build update
    timestamp = datetime.now().isoformat()
    lines = [f"## {timestamp}\n"]
    
    if not lessons:
        lines.append("No patterns detected in past 7 days.\n")
    else:
        for tag, lesson_list in sorted(lessons.items()):
            lines.append(f"\n**#{tag}**\n")
            for lesson in lesson_list:
                lines.append(f"- {lesson}\n")
    
    # Append to file
    with open(lessons_file, "a", encoding="utf-8") as f:
        f.write("".join(lines))
        f.write("\n")
    
    print(f"✓ Lessons extracted and written to {lessons_file}")
    return lessons_file


# ─────────────────────────────────────────────────────────────────────────────
# Main execution
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Extracting lessons from HFL corpus...")
    lessons_by_tag = extract_lessons_from_corpus(days_back=7)
    ranked = deduplicate_and_rank(lessons_by_tag)
    
    if ranked:
        print(f"Found patterns in {len(ranked)} tags")
        write_lessons_to_memory(ranked)
    else:
        print("No patterns detected")
