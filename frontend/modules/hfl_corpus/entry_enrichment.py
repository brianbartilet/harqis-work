"""Best-effort location and tag enrichment for manual corpus entries."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, time, timedelta
from typing import Any
from urllib.parse import quote_plus

import httpx

from modules.hfl_corpus.entry_create import CreateEntryRequest, _tags, _timestamp


_log = logging.getLogger(__name__)
_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_NOMINATIM_UA = (
    "harqis-work-hfl/1.0 (personal location journal; "
    "+https://github.com/brianbartilet/harqis-work)"
)
_TAG_TOKEN = re.compile(r"[^\w-]+", re.UNICODE)


def _owntracks_fix(when: datetime) -> tuple[float, float] | None:
    """Return the nearest OwnTracks fix from ``when``'s calendar day."""
    user = os.environ.get("OWN_TRACKS_DEFAULT_USER", "").strip()
    device = os.environ.get("OWN_TRACKS_DEFAULT_DEVICE", "").strip()
    if not user or not device:
        return None

    from apps.own_tracks.config import CONFIG as owntracks_config
    from apps.own_tracks.references.web.api.locations import (
        ApiServiceOwnTracksLocations,
    )

    start = datetime.combine(when.date(), time.min)
    end = start + timedelta(days=1)
    result = ApiServiceOwnTracksLocations(owntracks_config).get_history(
        user=user,
        device=device,
        from_ts=int(start.timestamp()),
        to_ts=int(end.timestamp()),
    )
    rows = (result or {}).get("data", []) if isinstance(result, dict) else []
    target = when.timestamp()
    candidates: list[tuple[float, float, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            latitude = float(row["lat"])
            longitude = float(row["lon"])
            recorded_at = float(row["tst"])
        except (KeyError, TypeError, ValueError):
            continue
        candidates.append((abs(recorded_at - target), latitude, longitude))
    if not candidates:
        return None
    _, latitude, longitude = min(candidates, key=lambda item: item[0])
    return latitude, longitude


def _short_place(data: dict[str, Any]) -> str:
    address = data.get("address") if isinstance(data.get("address"), dict) else {}
    name = str(data.get("name") or "").strip()
    road = str(address.get("road") or "").strip()
    locality = str(
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("city_district")
        or address.get("town")
        or address.get("village")
        or address.get("city")
        or ""
    ).strip()
    parts = list(dict.fromkeys(part for part in (name or road, locality) if part))
    if parts:
        return ", ".join(parts)[:80]
    display_name = str(data.get("display_name") or "").strip()
    return display_name.split(",", 1)[0][:80] if display_name else ""


def _reverse_geocode(latitude: float, longitude: float) -> str:
    response = httpx.get(
        _NOMINATIM_URL,
        params={
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "zoom": 16,
            "addressdetails": 1,
        },
        headers={"User-Agent": _NOMINATIM_UA},
        timeout=10.0,
    )
    response.raise_for_status()
    return _short_place(response.json())


def _location_reference(place: str) -> str:
    url = f"https://www.openstreetmap.org/search?query={quote_plus(place)}"
    return f"[{place}]({url})"


def _parse_tag_response(text: str) -> tuple[str, ...]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except (TypeError, ValueError):
        return ()
    raw_tags = payload.get("tags") if isinstance(payload, dict) else None
    if not isinstance(raw_tags, list):
        return ()
    normalized: list[str] = []
    for raw_tag in raw_tags:
        tag = _TAG_TOKEN.sub("-", str(raw_tag).strip().casefold()).strip("-_")
        if tag and tag not in normalized:
            normalized.append(tag)
        if len(normalized) == 5:
            break
    return tuple(normalized)


def _suggest_tags(payload: CreateEntryRequest, *, place: str = "") -> tuple[str, ...]:
    from apps.antropic.config import get_config as get_anthropic_config
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

    existing = _tags(payload.tags)
    prompt = "\n".join(
        (
            f"Moment: {payload.moment.strip()}",
            f"What happened: {payload.what_happened.strip()}",
            f"Why it stayed: {payload.why_it_stayed.strip()}",
            f"Possible use: {payload.possible_use.strip()}",
            f"Existing tags: {', '.join(existing)}",
            f"Place: {place or 'not available'}",
        )
    )
    service = BaseApiServiceAnthropic(get_anthropic_config("ANTHROPIC"))
    response = service.send_message(
        prompt=prompt,
        system=(
            "Suggest up to five concise contextual tags for this personal activity "
            "entry. Preserve privacy, avoid coordinates and names not present in the "
            "entry, and do not repeat the existing tags. Return only JSON in the form "
            '{"tags":["lowercase-kebab-case"]}.'
        ),
        model=_HAIKU_MODEL,
        max_tokens=180,
    )
    text = response.content[0].text if response and response.content else ""
    return _parse_tag_response(text)


def enrich_manual_entry(
    payload: CreateEntryRequest,
) -> tuple[CreateEntryRequest, dict[str, Any]]:
    """Return a reviewed payload enriched without making failures blocking."""
    entry_timestamp = _timestamp(payload)
    if not payload.moment.strip():
        raise ValueError("Moment is required.")
    if not payload.what_happened.strip():
        raise ValueError("What happened is required.")
    notices: list[str] = []
    location_source = "disabled"
    location_label = ""
    enriched = payload

    if payload.include_location:
        coordinates: tuple[float, float] | None = None
        try:
            coordinates = _owntracks_fix(entry_timestamp)
        except Exception as exc:  # noqa: BLE001 - enrichment is best effort
            _log.info("Manual entry OwnTracks lookup failed: %s", exc)
        if coordinates:
            location_source = "owntracks"
        elif payload.browser_latitude is not None and payload.browser_longitude is not None:
            coordinates = (payload.browser_latitude, payload.browser_longitude)
            location_source = "browser"

        if coordinates:
            try:
                location_label = _reverse_geocode(*coordinates)
            except Exception as exc:  # noqa: BLE001 - enrichment is best effort
                _log.info("Manual entry reverse geocoding failed: %s", exc)
            if location_label:
                references = list(enriched.reference_items())
                location_reference = _location_reference(location_label)
                if location_reference not in references:
                    references.append(location_reference)
                enriched = enriched.model_copy(
                    update={"references": "\n".join(references)}
                )
            else:
                location_source = "unavailable"
                notices.append("Location could not be named, so it was not added.")
        else:
            location_source = "unavailable"
            notices.append("Location was unavailable from OwnTracks and this browser.")

    added_tags: tuple[str, ...] = ()
    try:
        suggestions = _suggest_tags(enriched, place=location_label)
        existing = list(_tags(enriched.tags))
        existing_folded = {tag.casefold() for tag in existing}
        added_tags = tuple(
            tag for tag in suggestions if tag.casefold() not in existing_folded
        )[:5]
        if added_tags:
            enriched = enriched.model_copy(
                update={
                    "tags": " ".join(f"#{tag}" for tag in (*existing, *added_tags))
                }
            )
    except Exception as exc:  # noqa: BLE001 - manual tags must remain usable
        _log.warning("Manual entry contextual tag analysis failed: %s", exc)
        notices.append("Contextual tag analysis was unavailable; manual tags were kept.")

    enriched = enriched.model_copy(
        update={
            "browser_latitude": None,
            "browser_longitude": None,
            "browser_location_status": "",
        }
    )
    return enriched, {
        "location_source": location_source,
        "location_label": location_label,
        "added_tags": list(added_tags),
        "notices": notices,
    }
