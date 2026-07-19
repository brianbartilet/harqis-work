"""
workflows/hfl/tasks/analyze_media.py

Turn images and short videos that land in the daily-dumps inbox into
Homework-for-Life corpus entries, so visual moments flow into the weekly
`summarize_hfl_week` rollup.

Pipeline:
  1. Resolve the dumps inbox (same source `analyze_daily_dumps` uses).
  2. Walk it windowed by mtime — files modified in the last `window_days` —
     reserving bounded capacity for Android media before filling by recency.
  3. Images  → base64 vision block. Videos → N evenly-sampled frames
     (OpenCV) as a multi-image block.
  4. Haiku 4.5 returns a structured JSON story moment.
  5. Each non-skipped, not-yet-referenced result is appended to the corpus as
     one HFL entry, dated at the file's capture (mtime) time and tagged from
     the folder path. A `media_path` call targets one inbox artifact directly.

Cost: Haiku only — do NOT raise the Anthropic config default (shared by
Sonnet-class workflows). Frame count and `max_files` bound the vision spend.

Video support degrades gracefully: if OpenCV is unavailable, videos are
skipped (logged) and images are still processed.

Prompt lives in the prompts/ layer — workflows/hfl/prompts/analyze_media.md.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:
    import fcntl

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.dumps.config import get_dumps_target
from workflows.dumps.files import (
    CollectedFile,
    iter_recent_files,
    parse_dump_dir_name,
)
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import (
    _build_entry,
    append_entry,
    resolve_corpus_dir,
)
from workflows.hfl.tasks.ingest_location import (
    _osm_link,
    _reverse_geocode,
    nearest_fix,
)

_log = create_logger("hfl.analyze_media")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_SYSTEM_PROMPT = load_prompt("analyze_media").strip()

# OpenCV is an optional dependency — videos degrade to "skipped" without it.
try:  # pragma: no cover - import guard
    import cv2
    import numpy as np
    _HAVE_CV2 = True
except Exception:  # pragma: no cover - import guard
    cv2 = None
    np = None
    _HAVE_CV2 = False

# Pillow is optional too — EXIF GPS/timestamp enrichment degrades to
# OwnTracks-by-time (or no location) without it.
try:  # pragma: no cover - import guard
    from PIL import Image as _PILImage
    _HAVE_PIL = True
except Exception:  # pragma: no cover - import guard
    _PILImage = None
    _HAVE_PIL = False

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
_MEDIA_MAX_EDGE = 1568          # Anthropic's recommended max image edge
_RAW_IMAGE_MAX_BYTES = 4_500_000  # below the API's 5 MB/image hard limit

# Android canonical folder names used to classify dump-originated media.
# These appear in the relative path from the dumps inbox root.
_ANDROID_SCREENSHOT_DIRS = frozenset({"screenshots", "screenshot"})
_ANDROID_CAMERA_DIRS = frozenset({"camera", "dcim"})
_ANDROID_SCREENREC_DIRS = frozenset({"screen recordings", "screenrecord"})
_ANDROID_DUMP_SOURCES = frozenset({"nothing-phone"})
_ANDROID_CAPTURE_HINT = {
    "screenshot": "Source: Android screenshot\n",
    "photo": "Source: Android camera photo\n",
    "screen_recording": "Source: Android screen recording\n",
}


def classify_android_media_candidate(relative: Path) -> dict | None:
    """Classify a media file path as Android-origin and return source metadata.

    Reads only the folder path — never file contents. Returns a dict with
    ``capture_type`` ("screenshot", "photo", "screen_recording") and
    ``device_type`` ("android") when the first path component identifies a
    known Android dump source and later parent directories match canonical
    Android media folders. Returns None when unrecognised.

    Used to inject a ``Source:`` line into the Haiku instruction so the model
    can interpret app-UI screenshots, notification bars, and status icons as
    phone-specific story signals, without ever surfacing raw image text.
    """
    if len(relative.parts) < 2:
        return None
    parsed_source = parse_dump_dir_name(relative.parts[0].casefold())
    if not parsed_source or parsed_source[0] not in _ANDROID_DUMP_SOURCES:
        return None
    parts = frozenset(p.casefold() for p in relative.parts[1:-1])
    if parts & _ANDROID_SCREENSHOT_DIRS:
        return {"capture_type": "screenshot", "device_type": "android"}
    if parts & _ANDROID_CAMERA_DIRS:
        return {"capture_type": "photo", "device_type": "android"}
    if parts & _ANDROID_SCREENREC_DIRS:
        return {"capture_type": "screen_recording", "device_type": "android"}
    return None


def _select_media_candidates(
    collected: list[CollectedFile],
    *,
    max_files: int,
    android_min_files: int,
) -> list[CollectedFile]:
    """Reserve Android capacity, then fill unused slots by global recency."""
    limit = max(0, int(max_files))
    if limit == 0:
        return []
    candidates = sorted(
        (
            item for item in collected
            if item.path.suffix.lower() in _IMAGE_EXTS
            or item.path.suffix.lower() in _VIDEO_EXTS
        ),
        key=lambda item: item.mtime,
        reverse=True,
    )
    reserve = min(limit, max(0, int(android_min_files)))
    android = [
        item for item in candidates
        if classify_android_media_candidate(item.relative)
    ][:reserve]
    selected_paths = {item.path for item in android}
    selected = list(android)
    for item in candidates:
        if len(selected) >= limit:
            break
        if item.path not in selected_paths:
            selected.append(item)
            selected_paths.add(item.path)
    return sorted(selected, key=lambda item: item.mtime, reverse=True)


def _target_media_candidate(inbox: Path, media_path: str | Path) -> CollectedFile:
    """Build one validated inbox-relative media candidate for targeted ingest."""
    root = inbox.expanduser().resolve()
    path = Path(media_path).expanduser().resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"media path is outside dumps inbox: {path}") from exc
    if not path.is_file():
        raise ValueError(f"media path is not a file: {path}")
    if path.suffix.lower() not in (_IMAGE_EXTS | _VIDEO_EXTS):
        raise ValueError(f"unsupported media type: {path.suffix}")
    return CollectedFile(
        source_root=root,
        path=path,
        relative=relative,
        mtime=datetime.fromtimestamp(path.stat().st_mtime),
    )


def _revalidate_media_candidate(inbox: Path, item: CollectedFile) -> CollectedFile:
    """Resolve a selected path again immediately before reading it."""
    return _target_media_candidate(inbox, item.path)


def _windows_final_path(fd: int) -> Path:
    """Resolve the file actually bound to an open Windows descriptor."""
    if os.name != "nt":  # pragma: no cover - guarded by the Windows open path
        raise RuntimeError("Windows file-handle resolution requested on POSIX")

    get_final_path = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    size = 512
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = get_final_path(handle, buffer, size, 0)
        if length == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        if length < size:
            raw_path = buffer.value
            break
        size = length + 1

    if raw_path.startswith("\\\\?\\UNC\\"):
        raw_path = "\\\\" + raw_path[8:]
    elif raw_path.startswith("\\\\?\\"):
        raw_path = raw_path[4:]
    return Path(raw_path)


def _open_confined_media(root: Path, resolved: Path, relative: Path) -> int:
    """Open one media file without permitting a symlink/reparse-point escape."""
    if os.name == "nt":
        fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            opened_path = _windows_final_path(fd)
            opened_path.relative_to(root)
            if os.path.normcase(str(opened_path)) != os.path.normcase(str(resolved)):
                raise ValueError(f"media path changed during secure open: {resolved}")
        except Exception:
            os.close(fd)
            raise
        return fd

    nofollow = os.O_NOFOLLOW
    directory = os.O_DIRECTORY
    root_fd = os.open(root, os.O_RDONLY | directory)
    parent_fd = root_fd
    file_fd: int | None = None
    try:
        for component in relative.parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | directory | nofollow,
                dir_fd=parent_fd,
            )
            if parent_fd != root_fd:
                os.close(parent_fd)
            parent_fd = next_fd
        file_fd = os.open(
            relative.name,
            os.O_RDONLY | nofollow,
            dir_fd=parent_fd,
        )
        return file_fd
    except Exception:
        if file_fd is not None:
            os.close(file_fd)
        raise
    finally:
        if parent_fd != root_fd:
            os.close(parent_fd)
        os.close(root_fd)


def _secure_media_snapshot(
    inbox: Path, item: CollectedFile,
) -> tuple[Path, CollectedFile]:
    """Copy one confined file through a platform-secure descriptor.

    POSIX opens every path component relative to the inbox with ``O_NOFOLLOW``.
    Windows validates the final path bound to the open OS handle. The model and
    metadata readers consume the private snapshot, binding validation and read
    access to the same source descriptor on both platforms.
    """
    root = inbox.expanduser().resolve()
    resolved = item.path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"media path is outside dumps inbox: {resolved}") from exc
    if resolved.suffix.lower() not in (_IMAGE_EXTS | _VIDEO_EXTS):
        raise ValueError(f"unsupported media type: {resolved.suffix}")

    file_fd: int | None = _open_confined_media(root, resolved, relative)
    snapshot_path: Path | None = None
    success = False
    try:
        source_stat = os.fstat(file_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise ValueError(f"media path is not a regular file: {resolved}")
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=resolved.suffix, prefix="hfl-media-", delete=False,
        ) as snapshot:
            snapshot_path = Path(snapshot.name)
            with os.fdopen(file_fd, "rb") as source:
                file_fd = None
                shutil.copyfileobj(source, snapshot)
            snapshot.flush()
            os.fsync(snapshot.fileno())
        safe_item = CollectedFile(
            source_root=root,
            path=resolved,
            relative=relative,
            mtime=datetime.fromtimestamp(source_stat.st_mtime),
        )
        success = True
        return snapshot_path, safe_item
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if snapshot_path is not None and not success:
            snapshot_path.unlink(missing_ok=True)


def _completed_media_references(day_file: Path) -> set[str]:
    """Read references only from independently terminated Markdown entries."""
    if not day_file.is_file():
        return set()
    text = day_file.read_text(encoding="utf-8")
    starts = [match.start() for match in re.finditer(r"(?m)^## ", text)]
    references: set[str] = set()
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        block = text[start:end]
        if not block.endswith("\n\n"):
            continue
        references.update(
            line.strip()[2:]
            for line in block.splitlines()
            if line.strip().startswith("- ")
        )
    return references


def _media_reference_exists(day_file: Path, media_path: Path) -> bool:
    """Return whether a complete corpus entry references this media path."""
    return str(media_path.resolve()) in _completed_media_references(day_file)


def _media_state_paths(corpus_dir: Path, media_path: Path) -> tuple[Path, Path]:
    key = hashlib.sha256(str(media_path.resolve()).encode("utf-8")).hexdigest()
    state_dir = corpus_dir / ".media-ingest-state"
    return state_dir / f"{key}.lock", state_dir / f"{key}.done"


def _try_lock_fd(fd: int) -> bool:
    """Acquire a non-blocking advisory lock on one descriptor."""
    if os.name == "nt":
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise
        return True

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock_fd(fd: int) -> None:
    """Release a descriptor lock acquired by :func:`_try_lock_fd`."""
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _media_state_exists(corpus_dir: Path, media_path: Path) -> bool:
    """Return true for a completed path or a claim actively locked by a worker."""
    lock_path, done_path = _media_state_paths(corpus_dir, media_path)
    if done_path.exists():
        return True
    if not lock_path.exists():
        return False
    fd = os.open(lock_path, os.O_RDWR)
    try:
        if not _try_lock_fd(fd):
            return True
        _unlock_fd(fd)
        return False
    finally:
        os.close(fd)


def _acquire_media_claim(
    corpus_dir: Path, media_path: Path,
) -> tuple[Path, Path, int] | None:
    """Claim a media path with an FD-bound advisory lock.

    The lock is released automatically if the worker dies. Keeping ownership on
    the open descriptor avoids pathname check-then-act races during finalization.
    """
    lock_path, done_path = _media_state_paths(corpus_dir, media_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if done_path.exists():
        return None
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    if not _try_lock_fd(fd):
        os.close(fd)
        return None
    if done_path.exists():
        _unlock_fd(fd)
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, f"{media_path.resolve()}\n".encode("utf-8"))
    return lock_path, done_path, fd


def _finish_media_claim(claim: tuple[Path, Path, int], completed: bool) -> None:
    """Mark completion while holding the claim's FD-bound lock, then release."""
    lock_path, done_path, fd = claim
    try:
        if completed:
            done_fd = os.open(done_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(done_fd, b"done\n")
            finally:
                os.close(done_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        _log.warning("hfl.media: could not finalize claim %s — %s", lock_path, exc)
    finally:
        try:
            _unlock_fd(fd)
        finally:
            os.close(fd)


def _filter_processed_media(
    candidates: list[CollectedFile], corpus_dir: Path,
) -> tuple[list[CollectedFile], int]:
    """Remove corpus-referenced or claimed media before quota selection."""
    pending: list[CollectedFile] = []
    duplicates = 0
    references_by_day: dict[Path, set[str]] = {}
    seen_paths: set[Path] = set()
    for item in candidates:
        source_root = item.source_root.expanduser().resolve()
        canonical_path = item.path.expanduser().resolve()
        try:
            canonical_relative = canonical_path.relative_to(source_root)
        except ValueError as exc:
            raise OSError(f"media path escaped source root: {canonical_path}") from exc
        day_file = corpus_dir / f"{item.mtime:%Y-%m-%d}.md"
        if day_file not in references_by_day:
            references_by_day[day_file] = _completed_media_references(day_file)
        if (
            canonical_path in seen_paths
            or str(canonical_path) in references_by_day[day_file]
            or _media_state_exists(corpus_dir, canonical_path)
        ):
            duplicates += 1
        else:
            seen_paths.add(canonical_path)
            pending.append(CollectedFile(
                source_root=source_root,
                path=canonical_path,
                relative=canonical_relative,
                mtime=item.mtime,
            ))
    return pending, duplicates


def _media_type_for(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix.lower(), "image/jpeg")


def _image_block(media_type: str, data: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


def _downscale_jpeg(arr) -> bytes | None:
    """Resize an OpenCV BGR array so its long edge <= _MEDIA_MAX_EDGE, JPEG."""
    if arr is None:
        return None
    h, w = arr.shape[:2]
    longest = max(h, w)
    if longest > _MEDIA_MAX_EDGE:
        scale = _MEDIA_MAX_EDGE / float(longest)
        arr = cv2.resize(arr, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


def _encode_image(path: Path) -> dict | None:
    """One image → an Anthropic image content block (bounded in size)."""
    raw = path.read_bytes()
    if _HAVE_CV2:
        try:
            arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            jpeg = _downscale_jpeg(arr)
            if jpeg:
                return _image_block("image/jpeg", jpeg)
        except Exception as exc:  # fall through to raw
            _log.debug("cv2 decode failed for %s (%s) — sending raw", path, exc)
    if len(raw) > _RAW_IMAGE_MAX_BYTES:
        _log.info("Skipping oversized image (no cv2 to downscale): %s", path)
        return None
    return _image_block(_media_type_for(path.suffix), raw)


def _video_blocks(path: Path, frames_per_video: int) -> list[dict]:
    """Sample `frames_per_video` evenly-spaced frames as image blocks."""
    if not _HAVE_CV2:
        _log.info("OpenCV unavailable — skipping video %s", path)
        return []
    cap = cv2.VideoCapture(str(path))
    blocks: list[dict] = []
    try:
        if not cap.isOpened():
            _log.info("Could not open video %s", path)
            return []
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total > 0:
            step = max(1, total // max(1, frames_per_video))
            indices = list(range(0, total, step))[:frames_per_video]
            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
                if not ok:
                    continue
                jpeg = _downscale_jpeg(frame)
                if jpeg:
                    blocks.append(_image_block("image/jpeg", jpeg))
        else:  # frame count unknown — grab sequentially
            grabbed = 0
            while grabbed < frames_per_video:
                ok, frame = cap.read()
                if not ok:
                    break
                jpeg = _downscale_jpeg(frame)
                if jpeg:
                    blocks.append(_image_block("image/jpeg", jpeg))
                    grabbed += 1
                for _ in range(29):  # ~1 frame/sec at 30fps
                    if not cap.grab():
                        break
    finally:
        cap.release()
    return blocks


def _tags_from(relative: Path, media_kind: str) -> list[str]:
    """Folder-name pattern signal → tags (the 'patterns in folder names')."""
    tags: list[str] = [media_kind]
    for part in relative.parts[:-1]:  # exclude the filename itself
        cleaned = part.strip().lower().replace(" ", "-")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tags[:8]


def _parse_model_json(text: str) -> dict | None:
    """Tolerant JSON parse — strips ``` fences the model sometimes adds."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip().strip("`").strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def _validate_model_result(value: dict | None) -> dict | None:
    """Accept only the exact story-result schema; malformed output is retryable."""
    if not isinstance(value, dict) or type(value.get("skip")) is not bool:
        return None
    text_fields = ("moment", "what_happened", "why_it_stayed", "possible_use")
    if any(not isinstance(value.get(field), str) for field in text_fields):
        return None
    tags = value.get("tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        return None
    return value


def _dms_to_deg(dms, ref) -> float | None:
    """Convert an EXIF GPS (degrees, minutes, seconds) triple + N/S/E/W ref to
    signed decimal degrees, or None."""
    try:
        d, m, s = (float(x) for x in dms)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60.0 + s / 3600.0
    return -deg if str(ref).upper() in ("S", "W") else deg


def _exif_location_and_time(path: Path) -> tuple[tuple[float, float] | None, datetime | None]:
    """Best-effort ``(coords, capture_dt)`` from an image's EXIF.

    coords from the GPS IFD (when the camera recorded location), capture_dt
    from DateTimeOriginal (falling back to DateTime). Either may be None; any
    failure (no Pillow, no EXIF, unreadable) yields ``(None, None)``.
    """
    if not _HAVE_PIL:
        return None, None
    try:
        with _PILImage.open(path) as img:
            exif = img.getexif()
        if not exif:
            return None, None
        coords = None
        try:
            gps = exif.get_ifd(0x8825)  # GPSInfo IFD
        except Exception:  # noqa: BLE001
            gps = {}
        if gps:
            lat = _dms_to_deg(gps.get(2), gps.get(1))
            lon = _dms_to_deg(gps.get(4), gps.get(3))
            if lat is not None and lon is not None and (lat or lon):
                coords = (lat, lon)
        raw = None
        try:
            raw = exif.get_ifd(0x8769).get(36867)  # Exif IFD → DateTimeOriginal
        except Exception:  # noqa: BLE001
            raw = None
        raw = raw or exif.get(306)  # DateTime (main IFD)
        capture_dt = None
        if raw:
            try:
                capture_dt = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
            except ValueError:
                capture_dt = None
        return coords, capture_dt
    except Exception as exc:  # noqa: BLE001 - EXIF is best-effort
        _log.debug("hfl.media: EXIF read failed for %s (%s)", path, exc)
        return None, None


def _resolve_media_location(
    path: Path, mtime: datetime, is_image: bool, *, geocode_cache: dict
) -> tuple[str | None, tuple[float, float] | None, str | None]:
    """Resolve where a media file was captured → ``(place, coords, source)``.

    EXIF GPS first (most precise, the camera's own fix); otherwise the nearest
    OwnTracks fix to the capture time (EXIF DateTimeOriginal when present, else
    mtime) — which also geo-tags screenshots and EXIF-stripped media. The
    coordinate is reverse-geocoded to a place label (Nominatim, cached). All
    best-effort: any failure → ``(None, None, None)`` and the media is still
    analyzed, just without a place.
    """
    coords: tuple[float, float] | None = None
    source: str | None = None
    capture_dt = mtime
    try:
        if is_image:
            exif_coords, exif_dt = _exif_location_and_time(path)
            if exif_dt:
                capture_dt = exif_dt
            if exif_coords:
                coords, source = exif_coords, "exif"
        if coords is None:
            fix = nearest_fix(capture_dt)
            if fix:
                coords, source = fix, "owntracks"
        if coords:
            place = _reverse_geocode(coords[0], coords[1], cache=geocode_cache)
            return place, coords, source
    except Exception as exc:  # noqa: BLE001 - enrichment never breaks the pipeline
        _log.info("hfl.media: location enrich failed for %s (%s)", path, exc)
    return None, None, None


@SPROUT.task()
@log_result()
def analyze_hfl_media(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_files: int = 40,
    android_min_files: int = 10,
    frames_per_video: int = 4,
    max_tokens: int = 1024,
    media_path: str | None = None,
) -> dict[str, Any]:
    """Analyze recent or one targeted inbox media file and append HFL entries.

    The scheduled batch reserves ``android_min_files`` slots for Android-origin
    media, then fills unused capacity by global recency. ``media_path`` bypasses
    batch selection but must resolve inside the configured dumps inbox. Both
    modes skip a source path already referenced by its daily corpus file.

    Returns:
        {"entries_written", "images", "videos", "skipped", "scanned",
         "model", "window_days"}
    """
    target = get_dumps_target()
    if not target:
        _log.error("hfl.media: harqis_server_inbox not set — cannot scan")
        return {"skipped": "no inbox configured", "entries_written": 0}

    inbox = Path(target.inbox).expanduser()
    if not inbox.exists():
        _log.info("hfl.media: inbox %s does not exist yet", inbox)
        return {"skipped": "inbox missing", "entries_written": 0,
                "scanned": 0}

    if media_path:
        try:
            candidates = [_target_media_candidate(inbox, media_path)]
        except ValueError as exc:
            _log.info("hfl.media: targeted ingest rejected (%s)", exc)
            return {"skipped": "invalid media path", "reason": str(exc),
                    "entries_written": 0, "scanned": 0, "targeted": True}
        collected = candidates
    else:
        end = datetime.now()
        start = end - timedelta(days=window_days)
        collected = list(iter_recent_files([inbox], start, end))
        candidates = _select_media_candidates(
            collected, max_files=len(collected), android_min_files=0,
        )

    if not candidates:
        _log.info("hfl.media: no media in the last %d day(s)", window_days)
        return {"skipped": "no media", "entries_written": 0,
                "scanned": len(collected), "targeted": bool(media_path)}

    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    try:
        pending, duplicates = _filter_processed_media(candidates, corpus_dir)
    except OSError as exc:
        _log.error("hfl.media: cannot verify corpus idempotency — %s", exc)
        return {"skipped": "corpus unreadable", "reason": str(exc),
                "entries_written": 0, "scanned": 0,
                "targeted": bool(media_path)}

    if media_path:
        media = pending
        selected_count = 1
    else:
        media = _select_media_candidates(
            pending, max_files=max_files, android_min_files=android_min_files,
        )
        selected_count = len(media)
    if not media:
        return {"skipped": "already ingested", "entries_written": 0,
                "scanned": selected_count, "duplicates": duplicates,
                "targeted": bool(media_path)}

    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")

    images = videos = entries = skipped = android_items = 0
    geo_cache: dict = {}  # reverse-geocode cache shared across this run's media

    for item in media:
        try:
            item = _revalidate_media_candidate(inbox, item)
        except (OSError, ValueError) as exc:
            skipped += 1
            _log.warning("hfl.media: media path changed or escaped %s — %s", item.path, exc)
            continue
        try:
            claim = _acquire_media_claim(corpus_dir, item.path)
        except OSError as exc:
            skipped += 1
            _log.warning("hfl.media: cannot claim %s — %s", item.path, exc)
            continue
        if claim is None:
            duplicates += 1
            skipped += 1
            _log.info("hfl.media: already claimed — skipping %s", item.path)
            continue
        completed = False
        snapshot_path: Path | None = None
        suffix = item.path.suffix.lower()
        is_video = suffix in _VIDEO_EXTS
        try:
            snapshot_path, item = _secure_media_snapshot(inbox, item)
            if is_video:
                blocks = _video_blocks(snapshot_path, frames_per_video)
                media_kind = "video"
            else:
                one = _encode_image(snapshot_path)
                blocks = [one] if one else []
                media_kind = "image"

            if not blocks:
                skipped += 1
                continue

            place, coords, geo_src = _resolve_media_location(
                snapshot_path, item.mtime, not is_video, geocode_cache=geo_cache,
            )
            if place:
                loc_line = f"Location: {place}\n"
            elif coords:
                loc_line = f"Location: {coords[0]:.4f},{coords[1]:.4f}\n"
            else:
                loc_line = ""

            # Inject Android source classification so the model can interpret
            # phone-specific UI elements (status bar, app chrome, notifications)
            # as story context without exposing raw on-screen text to callers.
            android_meta = classify_android_media_candidate(item.relative)
            if android_meta:
                android_items += 1
                source_line = _ANDROID_CAPTURE_HINT.get(android_meta["capture_type"], "")
            else:
                source_line = ""

            instruction = {
                "type": "text",
                "text": (
                    f"File: {item.path.name}\n"
                    f"Captured: {item.mtime.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Folder path: {item.relative.as_posix()}\n"
                    f"{source_line}"
                    f"{loc_line}\n"
                    "Analyze this media per your instructions and reply with "
                    "the JSON object only."
                ),
            }
            response = client.send_messages(
                messages=[{"role": "user", "content": [*blocks, instruction]}],
                model=model,
                max_tokens=max_tokens,
                system=_SYSTEM_PROMPT,
            )
            text = response.content[0].text if response.content else ""
            parsed = _validate_model_result(_parse_model_json(text))

            if is_video:
                videos += 1
            else:
                images += 1

            if parsed and parsed.get("skip") is True:
                skipped += 1
                completed = True
                continue
            if not parsed or not str(parsed.get("moment", "")).strip():
                skipped += 1
                _log.warning("hfl.media: malformed model response for %s", item.path)
                continue

            tags = _tags_from(item.relative, media_kind)
            for t in parsed.get("tags") or []:
                t = str(t).strip().lstrip("#")
                if t and t not in tags:
                    tags.append(t)
            # Location enrichment → a place tag the corpus can be queried by.
            if place:
                place_tag = re.sub(r"[^a-z0-9]+", "-", place.split(",")[0].lower()).strip("-")
                if place_tag and place_tag not in tags:
                    tags.append(place_tag)
            # Android source metadata → device + capture-type tags so the
            # corpus is queryable by origin without surfacing raw image text.
            if android_meta:
                for atag in ("android", android_meta["capture_type"].replace("_", "-")):
                    if atag not in tags:
                        tags.append(atag)

            references = [str(item.path.resolve())]
            if coords:
                references.append(_osm_link(coords[0], coords[1]))

            entry = _build_entry(
                when=item.mtime,
                moment=str(parsed.get("moment", "")),
                what_happened=str(parsed.get("what_happened", "")),
                why_it_stayed=str(parsed.get("why_it_stayed", "")),
                possible_use=str(parsed.get("possible_use", "")),
                tags=tags,
                # Provenance: the source dump file (manifesto §1 — the
                # dumps→media→corpus loop) plus, when known, an OSM pin for
                # where it was captured (EXIF GPS or the OwnTracks fix).
                references=references,
            )
            day_file = corpus_dir / f"{item.mtime.strftime('%Y-%m-%d')}.md"
            # Vision pass = an LLM (Haiku) distillation → synthesized.
            append_entry(day_file, entry, source="media", synthesized=True)
            entries += 1
            completed = True
            _log.info("hfl.media: entry from %s → %s", item.path.name, day_file)

        except Exception as exc:  # one bad file must not abort the batch
            skipped += 1
            _log.warning("hfl.media: failed on %s — %s", item.path, exc)
            continue
        finally:
            if snapshot_path is not None:
                snapshot_path.unlink(missing_ok=True)
            _finish_media_claim(claim, completed)

    _log.info(
        "hfl.media: %d entries (%d images, %d videos, %d skipped) from %d media",
        entries, images, videos, skipped, len(media),
    )
    return {
        "entries_written": entries,
        "images": images,
        "videos": videos,
        "skipped": skipped,
        "scanned": selected_count,
        "duplicates": duplicates,
        "android_items": android_items,
        "model": model,
        "window_days": window_days,
        "targeted": bool(media_path),
    }
