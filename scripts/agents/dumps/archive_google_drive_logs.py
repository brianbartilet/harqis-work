#!/usr/bin/env python3
"""Archive downloaded Drive logs with verified copies and per-file failures.

Usage: python scripts/agents/dumps/archive_google_drive_logs.py
       --source <Drive-LOGS> --destination <archive> [--require-mount <volume>] [--dry-run]
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import errno
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

TRANSIENT = {errno.EAGAIN, errno.EBUSY, errno.EINTR, errno.ETIMEDOUT, errno.EDEADLK}
BLOCK = 1024 * 1024


def fingerprint(path):
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Not a regular file')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as reader:
        for chunk in iter(lambda: reader.read(BLOCK), b''):
            result.update(chunk)
    return result.digest()


@contextmanager
def archive_lock(destination):
    """OS releases the lock on exit or crash; no stale lock-file deletion needed."""
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / '.archive.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.write(b'0'); handle.flush(); handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def choose_destination(destination, checksum):
    """Reuse only a complete identical file; preserve all conflicting archives."""
    candidate = destination
    suffix = datetime.now().strftime('%Y%m%d-%H%M%S')
    index = 0
    while candidate.exists() or candidate.is_symlink():
        if not candidate.is_symlink() and candidate.is_file() and digest(candidate) == checksum:
            return candidate, True
        index += 1
        candidate = destination.with_name(f'{destination.stem}__archived_{suffix}_{index}{destination.suffix}')
    return candidate, False


def copy_verified(source, destination):
    before = fingerprint(source)
    # Refuse symbolic links in destination ancestry, including nested folders.
    for parent in (destination.parent, *destination.parent.parents):
        if parent.is_symlink():
            raise ValueError('Archive directory must not be a symbolic link')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.archive-', suffix='.partial', dir=destination.parent)
        temporary = Path(name)
        checksum = hashlib.sha256()
        with os.fdopen(fd, 'wb') as writer, source.open('rb') as reader:
            for chunk in iter(lambda: reader.read(BLOCK), b''):
                writer.write(chunk)
                checksum.update(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        expected = checksum.digest()
        if digest(temporary) != expected or temporary.stat().st_size != before[2]:
            raise ValueError('Archive copy verification failed; source retained')
        if fingerprint(source) != before or digest(source) != expected or fingerprint(source) != before:
            raise ValueError('Source changed during copy; source retained')
        target, already_archived = choose_destination(destination, expected)
        if not already_archived:
            # Same-filesystem atomic publication. All instances take archive_lock.
            temporary.rename(target)
            temporary = None
        if digest(target) != expected or fingerprint(source) != before:
            raise ValueError('Final verification failed; source retained')
        if os.name != 'nt':
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        source.unlink()
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def archive_file(source, destination, *, attempts=3, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            return copy_verified(source, destination)
        except OSError as exc:
            if exc.errno not in TRANSIENT or attempt == attempts - 1:
                raise
            sleep(2 ** attempt)


def archive(source, destination, *, dry_run=False):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Source must be an existing directory, not a symbolic link')
    src, dst = source.resolve(), destination.resolve()
    if src == dst or src in dst.parents or dst in src.parents:
        raise ValueError('Source and archive directories must not overlap')
    # Normalize OS aliases such as macOS /var -> /private/var once, while still
    # rejecting links introduced inside the archive tree during traversal.
    source, destination = src, dst
    count, failures = 0, []

    def failed(path, exc):
        failures.append((path, str(exc)))
        print(f'FAILED {path}: {exc}', file=sys.stderr)

    def walk_error(exc):
        failed(exc.filename or source, exc)

    def process():
        nonlocal count
        for root, directories, files in os.walk(source, topdown=False, onerror=walk_error, followlinks=False):
            for name in sorted(files):
                path = Path(root) / name
                if name == '.DS_Store':
                    continue
                try:
                    if path.is_symlink():
                        raise ValueError('Symbolic link skipped; source retained')
                    relative = path.relative_to(source)
                    if dry_run:
                        print(f'Would archive: {relative}')
                    else:
                        target = archive_file(path, destination / relative)
                        print(f'Archived: {relative} -> {target.relative_to(destination)}')
                    count += 1
                except (OSError, ValueError) as exc:
                    failed(path, exc)
            for name in directories:
                path = Path(root) / name
                if path.is_symlink():
                    failed(path, 'Symbolic link skipped; source retained')
                elif not dry_run:
                    try:
                        path.rmdir()  # Only remove empty directories, never recursively.
                    except OSError as exc:
                        if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                            failed(path, exc)
    if dry_run:
        process()
    else:
        with archive_lock(destination):
            process()
    print(f'{"Would archive" if dry_run else "Archived"} {count} files; {len(failures)} failures')
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--require-mount', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.require_mount and not args.require_mount.is_mount():
            raise ValueError(f'Required archive volume is not mounted: {args.require_mount}')
        return archive(args.source, args.destination, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f'Archive failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
