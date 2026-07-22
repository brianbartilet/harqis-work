#!/usr/bin/env python3
"""Archive completed HFL corpus months into ``YYYY/Mon`` directories.

Only Markdown files directly under the corpus root are candidates. Hidden files,
subdirectories, symlinks, current-month documents, undated documents, and
conflicting destinations are left untouched. Dates come from document metadata,
Markdown titles, HFL entry headers, ISO-week summary titles, or filenames; file
mtime/ctime is intentionally never used.
"""
from __future__ import annotations

import argparse
import errno
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})[-./](0[1-9]|1[0-2])[-./](0[1-9]|[12]\d|3[01])(?!\d)")
_ISO_WEEK = re.compile(r"(?<!\d)((?:19|20)\d{2})-W(0[1-9]|[1-4]\d|5[0-3])(?!\d)", re.IGNORECASE)
_FRONTMATTER_FIELD = re.compile(
    r"^(created|created_at|creation_date|date|title)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^#{1,2}\s+(.+?)\s*$", re.MULTILINE)
_MONTH_FOLDERS = (
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


@dataclass(frozen=True)
class ArchiveResult:
    moved: int
    current_month: int
    undated: tuple[str, ...]
    conflicts: tuple[str, ...]
    skipped_hidden: int = 0


def _move_exclusive(source: Path, destination: Path) -> None:
    """Move without overwrite, falling back when the volume has no hard links."""
    try:
        os.link(source, destination)
    except FileExistsError:
        raise
    except OSError as exc:
        unsupported = {errno.EXDEV, errno.EPERM, errno.ENOTSUP}
        if hasattr(errno, "EOPNOTSUPP"):
            unsupported.add(errno.EOPNOTSUPP)
        if exc.errno not in unsupported:
            raise

        fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            source.stat().st_mode & 0o777,
        )
        try:
            with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
            shutil.copystat(source, destination, follow_symlinks=False)
            if destination.stat().st_size != source.stat().st_size:
                raise OSError("archive fallback copy size mismatch")
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            destination.unlink(missing_ok=True)
            raise
    source.unlink()


def _date_in(value: str) -> date | None:
    match = _DATE.search(value)
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    week = _ISO_WEEK.search(value)
    if week:
        try:
            return date.fromisocalendar(int(week.group(1)), int(week.group(2)), 1)
        except ValueError:
            return None
    return None


def _frontmatter_values(text: str) -> list[tuple[str, str]]:
    if not text.startswith("---"):
        return []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    values: list[tuple[str, str]] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = _FRONTMATTER_FIELD.match(line)
        if match:
            values.append((match.group(1).casefold(), match.group(2).strip().strip("'\"")))
    return values


def document_date(path: Path) -> date | None:
    """Return a content/title date without consulting filesystem timestamps."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    metadata = _frontmatter_values(text)
    for field in ("created", "created_at", "creation_date", "date"):
        for key, value in metadata:
            if key == field and (parsed := _date_in(value)):
                return parsed
    for key, value in metadata:
        if key == "title" and (parsed := _date_in(value)):
            return parsed

    heading = _HEADING.search(text)
    if heading and (parsed := _date_in(heading.group(1))):
        return parsed
    return _date_in(path.stem)


def archive_corpus(
    root: str | Path,
    *,
    today: date | None = None,
    dry_run: bool = False,
) -> ArchiveResult:
    corpus_root = Path(root).expanduser().resolve()
    if not corpus_root.is_dir():
        raise NotADirectoryError(f"Corpus root is not a directory: {corpus_root}")

    current = today or date.today()
    current_month_start = current.replace(day=1)
    moved = 0
    current_month = 0
    hidden = 0
    undated: list[str] = []
    conflicts: list[str] = []

    for source in sorted(corpus_root.iterdir(), key=lambda item: item.name.casefold()):
        if source.name.startswith("."):
            hidden += int(source.is_file() and source.suffix.casefold() == ".md")
            continue
        if source.suffix.casefold() != ".md" or not source.is_file() or source.is_symlink():
            continue
        created = document_date(source)
        if created is None:
            undated.append(source.name)
            continue
        if created >= current_month_start:
            current_month += 1
            continue

        destination = (
            corpus_root
            / f"{created.year:04d}"
            / _MONTH_FOLDERS[created.month]
            / source.name
        )
        if destination.exists() or destination.is_symlink():
            conflicts.append(source.name)
            continue
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                _move_exclusive(source, destination)
            except FileExistsError:
                conflicts.append(source.name)
                continue
        moved += 1

    return ArchiveResult(
        moved=moved,
        current_month=current_month,
        undated=tuple(undated),
        conflicts=tuple(conflicts),
        skipped_hidden=hidden,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move prior-month root Markdown files into YYYY/Mon directories."
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("HFL_CORPUS_PATH", "/Volumes/harqis-data/hfl"),
        help="Canonical HFL corpus root (default: HFL_CORPUS_PATH or /Volumes/harqis-data/hfl).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report moves without changing files.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = archive_corpus(args.root, dry_run=args.dry_run)
    mode = "would move" if args.dry_run else "moved"
    print(
        f"HFL corpus archive: {mode} {result.moved}; "
        f"kept current month {result.current_month}; "
        f"undated {len(result.undated)}; conflicts {len(result.conflicts)}; "
        f"hidden skipped {result.skipped_hidden}"
    )
    if result.undated:
        print("Undated: " + ", ".join(result.undated))
    if result.conflicts:
        print("Conflicts: " + ", ".join(result.conflicts))
    return 1 if result.conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
