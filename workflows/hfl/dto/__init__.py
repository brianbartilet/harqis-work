"""Formal DTOs for the Homework-for-Life workflow.

The HFL corpus is Markdown (one file per day, `## ` headers split
entries — see workflows/hfl/tasks/retrieve.py). `HflEntry` is the
structured form of one such entry: it is the single source of truth for
the on-disk format. `_render_entry` in capture.py delegates here, so every
producer (capture, analyze_media, ingest_*) emits an identical, parseable
shape and `summarize`/`retrieve` can round-trip it back to fields.

This is the manifesto's CODE/Distill rule applied to lived experience:
"structured DTOs over raw API blobs" (docs/MANIFESTO.md §1).
"""

from workflows.hfl.dto.entry import HflEntry

__all__ = ["HflEntry"]
