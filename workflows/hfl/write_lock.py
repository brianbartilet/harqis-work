"""Cross-process serialization for corpus-wide HFL mutations."""

from __future__ import annotations

from pathlib import Path

from filelock import BaseFileLock, FileLock


def corpus_write_lock(corpus_dir: Path, *, timeout: float = 30) -> BaseFileLock:
    """Return the canonical lock held across Markdown and ES persistence."""
    root = Path(corpus_dir).expanduser().resolve()
    lock_dir = root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return FileLock(lock_dir / "corpus-write.lock", timeout=timeout)
