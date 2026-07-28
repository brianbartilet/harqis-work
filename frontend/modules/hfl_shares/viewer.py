"""Safe classification, text loading, and thumbnails for shared references."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from config import get_settings


MAX_PREVIEW_BYTES = 10 * 1024 * 1024
MAX_THUMBNAIL_PIXELS = 40_000_000
THUMBNAIL_WIDTH = 640
THUMBNAIL_HEIGHT = 360
THUMBNAIL_CACHE_FILES = 512
THUMBNAIL_CACHE_BYTES = 128 * 1024 * 1024

_IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
}
_VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
_MARKDOWN_EXTENSIONS = {".md", ".markdown"}
_TEXT_EXTENSIONS = {
    ".txt",
    ".log",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".ts",
    ".css",
    ".html",
    ".xml",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
    ".ps1",
    ".sql",
}


@dataclass(frozen=True)
class PreviewFile:
    kind: str
    media_type: str
    size: int


def _detected_image_type(header: bytes) -> str:
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if (
        len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    ):
        return "image/webp"
    if len(header) >= 16 and header[4:8] == b"ftyp":
        brands = header[8:64]
        if b"avif" in brands or b"avis" in brands:
            return "image/avif"
    return ""


def _detected_video_type(header: bytes) -> str:
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brands = header[8:64]
        if b"avif" not in brands and b"avis" not in brands:
            return "video/mp4"
    return ""


def _looks_like_utf8_text(sample: bytes) -> bool:
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def classify_preview(path: Path) -> PreviewFile | None:
    """Classify only when an allowlisted extension agrees with file content."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(65_536)
    except OSError:
        return None
    extension = path.suffix.casefold()
    if extension in _IMAGE_TYPES:
        expected = _IMAGE_TYPES[extension]
        if size <= MAX_PREVIEW_BYTES and _detected_image_type(header) == expected:
            return PreviewFile("image", expected, size)
        return None
    if extension in _VIDEO_TYPES:
        expected = _VIDEO_TYPES[extension]
        if _detected_video_type(header) == expected:
            return PreviewFile("video", expected, size)
        return None
    if extension in _MARKDOWN_EXTENSIONS:
        if size <= MAX_PREVIEW_BYTES and _looks_like_utf8_text(header):
            return PreviewFile("markdown", "text/markdown; charset=utf-8", size)
        return None
    if extension in _TEXT_EXTENSIONS:
        if size <= MAX_PREVIEW_BYTES and _looks_like_utf8_text(header):
            return PreviewFile("text", "text/plain; charset=utf-8", size)
    return None


def read_preview_text(path: Path) -> str:
    if path.stat().st_size > MAX_PREVIEW_BYTES:
        raise ValueError("This file is too large to preview.")
    return path.read_text(encoding="utf-8")


def _thumbnail_cache_dir() -> Path:
    store = Path(get_settings().hfl_share_store_path).expanduser().resolve()
    return store.parent / "hfl-share-thumbnails"


def _thumbnail_key(path: Path, preview: PreviewFile) -> str:
    stat = path.stat()
    fingerprint = (
        f"{path.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}\0{preview.kind}"
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _prune_cache(cache_dir: Path) -> None:
    try:
        files = sorted(
            (item for item in cache_dir.glob("*.jpg") if item.is_file()),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        total = 0
        for index, item in enumerate(files):
            size = item.stat().st_size
            total += size
            if index >= THUMBNAIL_CACHE_FILES or total > THUMBNAIL_CACHE_BYTES:
                item.unlink(missing_ok=True)
    except OSError:
        return


def _scaled_frame(frame):
    import cv2

    height, width = frame.shape[:2]
    if width <= 0 or height <= 0 or width * height > MAX_THUMBNAIL_PIXELS:
        raise ValueError("Media dimensions are unsafe to thumbnail.")
    scale = min(THUMBNAIL_WIDTH / width, THUMBNAIL_HEIGHT / height, 1.0)
    if scale < 1.0:
        frame = cv2.resize(
            frame,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return frame


def thumbnail_path(path: Path, preview: PreviewFile) -> Path | None:
    """Return a private cached JPEG thumbnail, or None when decoding fails."""
    if preview.kind not in {"image", "video"}:
        return None
    try:
        import cv2

        cache_dir = _thumbnail_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        destination = cache_dir / f"{_thumbnail_key(path, preview)}.jpg"
        if destination.is_file():
            os.utime(destination, None)
            return destination
        cv2.setNumThreads(1)
        if preview.kind == "image":
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        else:
            capture = cv2.VideoCapture(str(path))
            try:
                width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if width * height > MAX_THUMBNAIL_PIXELS:
                    return None
                frame = None
                for _ in range(12):
                    ok, candidate = capture.read()
                    if ok and candidate is not None:
                        frame = candidate
                        break
            finally:
                capture.release()
        if frame is None:
            return None
        frame = _scaled_frame(frame)
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 78],
        )
        if not ok:
            return None
        temporary = destination.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_bytes(encoded.tobytes())
        os.replace(temporary, destination)
        _prune_cache(cache_dir)
        return destination
    except Exception:
        # Media decoders can raise backend-specific exceptions. Thumbnailing is
        # optional, so any decoder/cache failure must degrade to the safe tile.
        return None
