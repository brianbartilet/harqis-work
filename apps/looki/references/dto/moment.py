from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Optional


_MOMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_URL_RE = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]{1,31}://|www\.)[^\s<>\"']+"
)
_NUMBER = r"[+-]?\d{1,3}(?:\.\d+)?"


def contains_precise_coordinates(value: str) -> bool:
    """Detect common decimal and directional DMS latitude/longitude pairs."""
    text = str(value)

    labelled: dict[str, float] = {}
    for match in re.finditer(
        rf"(?i)\b(lat(?:itude)?|lon(?:gitude)?|lng)\s*[:=]\s*({_NUMBER})",
        text,
    ):
        kind = "lat" if match.group(1).lower().startswith("lat") else "lon"
        labelled[kind] = float(match.group(2))
    if (
        "lat" in labelled
        and "lon" in labelled
        and abs(labelled["lat"]) <= 90
        and abs(labelled["lon"]) <= 180
    ):
        return True

    # Decimal/GeoJSON pairs may be latitude-first or longitude-first.
    for match in re.finditer(
        r"(?i)(?<![\w.])([+-]?\d{1,3}\.\d+)\s*°?\s*[NSEW]?"
        r"\s*[,;/]\s*([+-]?\d{1,3}\.\d+)\s*°?\s*[NSEW]?(?!\w)",
        text,
    ):
        first, second = (abs(float(part)) for part in match.groups())
        if (first <= 90 and second <= 180) or (first <= 180 and second <= 90):
            return True

    # Common DMS forms, including longitude-first order. Direction letters are
    # required so ordinary prose containing several integers is not discarded.
    dms = re.compile(
        r"(?i)(?<!\w)(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*"
        r"(\d{1,2}(?:\.\d+)?)\s*(?:[\"″]\s*)?([NSEW])(?!\w)"
    )
    directions: set[str] = set()
    for degrees, minutes, seconds, direction in dms.findall(text):
        limit = 90 if direction.upper() in {"N", "S"} else 180
        if int(degrees) <= limit and int(minutes) < 60 and float(seconds) < 60:
            directions.add(direction.upper())
    return bool(directions & {"N", "S"}) and bool(directions & {"E", "W"})


def scrub_url_string(value: str) -> str:
    """Remove URLs even when wrapped in Markdown, punctuation, or assignments."""
    return _URL_RE.sub("[external-url-omitted]", value)


def safe_moment_text(value: object) -> Optional[str]:
    """Return a privacy-safe scalar string, or omit coordinate-bearing text."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    if not text or contains_precise_coordinates(text):
        return None
    return scrub_url_string(text)


def valid_moment_id(value: object) -> Optional[str]:
    """Return an exact Markdown-safe source ID, or ``None``.

    IDs are identities, so this deliberately does not strip, slug, or otherwise
    normalize malformed vendor values into a different identity.
    """
    if not isinstance(value, str) or not _MOMENT_ID_RE.fullmatch(value):
        return None
    return value


@dataclass(frozen=True)
class DtoLookiMoment:
    """Privacy-bounded metadata for one Looki moment.

    Looki-generated text is deliberately named ``generated_text`` so callers do
    not mistake it for a verified transcript. Exact coordinates and temporary
    media URLs are not represented by this DTO and therefore cannot leak into
    the normal HFL path.
    """

    id: Optional[str] = None
    title: Optional[str] = None
    generated_text: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    timezone: Optional[str] = None
    location_label: Optional[str] = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_safe_dict(self) -> dict:
        safe_id = valid_moment_id(self.id)
        if safe_id is not None and safe_moment_text(safe_id) != safe_id:
            safe_id = None
        safe_tags = []
        for tag in self.tags:
            safe = safe_moment_text(tag)
            if safe and "[external-url-omitted]" not in safe and safe not in safe_tags:
                safe_tags.append(safe)
        return {
            "id": safe_id,
            "title": safe_moment_text(self.title),
            "generated_text": safe_moment_text(self.generated_text),
            "started_at": safe_moment_text(self.started_at),
            "ended_at": safe_moment_text(self.ended_at),
            "timezone": safe_moment_text(self.timezone),
            "location_label": safe_moment_text(self.location_label),
            "tags": safe_tags,
            "generated_text_verified": False,
        }
