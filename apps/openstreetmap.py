"""Pure OpenStreetMap helpers shared by frontend and workflow producers."""

from __future__ import annotations

import math
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_FALLBACK_LOCK = threading.Lock()


def osm_link(latitude: float, longitude: float) -> str:
    """Return the canonical HARQIS OpenStreetMap pin for validated coordinates."""
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("Coordinates are outside valid latitude/longitude bounds.")
    return (
        f"https://www.openstreetmap.org/?mlat={latitude:.5f}&mlon={longitude:.5f}"
        f"#map=16/{latitude:.5f}/{longitude:.5f}"
    )


def _rate_file() -> Path:
    user_id = (
        str(os.getuid())
        if hasattr(os, "getuid")
        else os.environ.get("USERNAME", "user")
    )
    configured = os.environ.get("HARQIS_NOMINATIM_RATE_FILE", "").strip()
    return (
        Path(configured)
        if configured
        else Path(tempfile.gettempdir()) / f"harqis-nominatim-{user_id}.rate"
    )


@contextmanager
def _exclusive_file(fd: int) -> Iterator[None]:
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


def nominatim_rate_limit(*, min_interval: float = 1.1) -> None:
    """Pace Nominatim calls across frontend/workflow threads and OS processes."""
    interval = max(float(min_interval), 1.0)
    path = _rate_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    with _FALLBACK_LOCK:
        fd = os.open(path, flags, 0o600)
        try:
            with _exclusive_file(fd):
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, 64).decode("ascii", errors="ignore").strip()
                try:
                    last_request = float(raw or "0")
                except ValueError:
                    last_request = 0.0
                now = time.time()
                if not math.isfinite(last_request) or last_request > now + interval:
                    last_request = 0.0
                wait = last_request + interval - now
                if wait > 0:
                    time.sleep(min(wait, interval))
                current = f"{time.time():.6f}".encode("ascii")
                os.lseek(fd, 0, os.SEEK_SET)
                os.ftruncate(fd, 0)
                os.write(fd, current)
                os.fsync(fd)
        finally:
            os.close(fd)
