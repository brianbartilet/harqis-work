"""
workflows/hfl/tasks/analyze_media.py

Turn images and short videos that land in the daily-dumps inbox into
Homework-for-Life corpus entries, so visual moments flow into the weekly
`summarize_hfl_week` rollup.

Pipeline:
  1. Resolve the dumps inbox (same source `analyze_daily_dumps` uses).
  2. Walk it windowed by mtime — files modified in the last `window_days`
     (stateless: overlapping runs may re-analyze; the daily window + daily
     schedule keeps overlap negligible).
  3. Images  → base64 vision block. Videos → N evenly-sampled frames
     (OpenCV) as a multi-image block.
  4. Haiku 4.5 returns a structured JSON story moment.
  5. Each non-skipped result is appended to the corpus as one HFL entry,
     dated at the file's capture (mtime) time, tagged from the folder path.

Cost: Haiku only — do NOT raise the Anthropic config default (shared by
Sonnet-class workflows). Frame count and `max_files` bound the vision spend.

Video support degrades gracefully: if OpenCV is unavailable, videos are
skipped (logged) and images are still processed.

Prompt lives in the prompts/ layer — workflows/hfl/prompts/analyze_media.md.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.dumps.config import get_dumps_target
from workflows.dumps.files import iter_recent_files
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
    frames_per_video: int = 4,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Analyze recent inbox media and append HFL corpus entries.

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

    end = datetime.now()
    start = end - timedelta(days=window_days)
    collected = sorted(
        iter_recent_files([inbox], start, end),
        key=lambda c: c.mtime,
        reverse=True,
    )
    media = [
        c for c in collected
        if c.path.suffix.lower() in _IMAGE_EXTS
        or c.path.suffix.lower() in _VIDEO_EXTS
    ][:max_files]

    if not media:
        _log.info("hfl.media: no media in the last %d day(s)", window_days)
        return {"skipped": "no media", "entries_written": 0,
                "scanned": len(collected)}

    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")

    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)

    images = videos = entries = skipped = 0
    geo_cache: dict = {}  # reverse-geocode cache shared across this run's media

    for item in media:
        suffix = item.path.suffix.lower()
        is_video = suffix in _VIDEO_EXTS
        try:
            if is_video:
                blocks = _video_blocks(item.path, frames_per_video)
                media_kind = "video"
            else:
                one = _encode_image(item.path)
                blocks = [one] if one else []
                media_kind = "image"

            if not blocks:
                skipped += 1
                continue

            place, coords, geo_src = _resolve_media_location(
                item.path, item.mtime, not is_video, geocode_cache=geo_cache,
            )
            if place:
                loc_line = f"Location: {place}\n"
            elif coords:
                loc_line = f"Location: {coords[0]:.4f},{coords[1]:.4f}\n"
            else:
                loc_line = ""

            instruction = {
                "type": "text",
                "text": (
                    f"File: {item.path.name}\n"
                    f"Captured: {item.mtime.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Folder path: {item.relative.as_posix()}\n"
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
            parsed = _parse_model_json(text)

            if is_video:
                videos += 1
            else:
                images += 1

            if not parsed or parsed.get("skip") or not str(
                parsed.get("moment", "")
            ).strip():
                skipped += 1
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

            references = [str(item.path)]
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
            _log.info("hfl.media: entry from %s → %s", item.path.name, day_file)

        except Exception as exc:  # one bad file must not abort the batch
            skipped += 1
            _log.warning("hfl.media: failed on %s — %s", item.path, exc)
            continue

    _log.info(
        "hfl.media: %d entries (%d images, %d videos, %d skipped) from %d media",
        entries, images, videos, skipped, len(media),
    )
    return {
        "entries_written": entries,
        "images": images,
        "videos": videos,
        "skipped": skipped,
        "scanned": len(media),
        "model": model,
        "window_days": window_days,
    }
