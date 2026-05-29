"""
workflows/hfl/tasks/ingest_location.py

Daily location-timeline -> HFL corpus. Pulls the day's GPS track from the
local OwnTracks Recorder (apps/own_tracks), clusters the fixes into
*stay-points* (places where the operator dwelled), reverse-geocodes each stay
to a place name via OpenStreetMap Nominatim (free, no key), and distils the
day's movement into ONE Homework-for-Life entry — a "where I was today"
timeline — dual-written to the Markdown corpus + the harqis-hfl-entries ES
index.

Source: the OwnTracks Recorder REST API (apps/own_tracks ::
ApiServiceOwnTracksLocations.get_history). Which device is read is set by
OWN_TRACKS_DEFAULT_USER / OWN_TRACKS_DEFAULT_DEVICE (.env/apps.env),
overridable per-call. No device configured, Recorder unreachable, or no fixes
in the window -> clean no-op (no LLM, no entry; the beat never breaks). A
window with fixes but no qualifying stay-points writes a lightweight
movement-only entry so GPS-active days do not silently disappear.

Reverse geocoding honours the Nominatim usage policy: a descriptive
User-Agent, <=1 request/second, and results cached per rounded coordinate
within a run. Any geocode failure degrades to coordinates-only — the entry
still renders.

Cost: Haiku only — never raise the Anthropic DEFAULT_MODEL. No LLM call on an
empty window or movement-only fallback.

The collectors (collect_location_activity / distill_location_activity) are
plain functions so the MCP tool (workflows/hfl/mcp.py :: location_activity)
can reuse them for a live, no-write view.
"""

from __future__ import annotations

import math
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.own_tracks.config import CONFIG as OWN_TRACKS_CONFIG
from apps.own_tracks.references.web.api.locations import ApiServiceOwnTracksLocations

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import (
    _build_entry,
    append_entry,
    resolve_corpus_dir,
)
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_location")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_NOMINATIM_UA = (
    "harqis-work-hfl/1.0 (personal location journal; "
    "+https://github.com/brianbartilet/harqis-work)"
)
# Module-level throttle so back-to-back stay lookups respect Nominatim's
# <=1 req/s policy across the whole run.
_LAST_GEOCODE_TS = 0.0


# ── geo helpers ───────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _osm_link(lat: float, lon: float) -> str:
    """A shareable OpenStreetMap pin for a coordinate (the entry's provenance)."""
    return (
        f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}"
        f"#map=16/{lat:.5f}/{lon:.5f}"
    )


def _short_place(data: dict) -> Optional[str]:
    """A compact human label from a Nominatim reverse response, or None."""
    if not isinstance(data, dict):
        return None
    name = (data.get("name") or "").strip()
    addr = data.get("address") or {}
    road = (addr.get("road") or "").strip()
    locality = (
        addr.get("suburb") or addr.get("neighbourhood") or addr.get("city_district")
        or addr.get("town") or addr.get("village") or addr.get("city") or ""
    ).strip()
    parts = [p for p in (name or road, locality) if p]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    if seen:
        return ", ".join(seen)[:80]
    dn = (data.get("display_name") or "").strip()
    return dn.split(",")[0][:80] if dn else None


def _reverse_geocode(
    lat: float, lon: float, *, cache: dict, min_interval: float = 1.1
) -> Optional[str]:
    """Resolve lat/lon -> a short place label via Nominatim. Best-effort: any
    failure (offline, rate-limited, parse) returns None and the caller keeps
    the coordinates. Cached per ~100 m cell within the run; throttled to honour
    the Nominatim usage policy (<=1 req/s)."""
    global _LAST_GEOCODE_TS
    key = (round(lat, 3), round(lon, 3))  # ~100 m grid
    if key in cache:
        return cache[key]
    try:
        import httpx

        wait = _LAST_GEOCODE_TS + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        resp = httpx.get(
            _NOMINATIM_URL,
            params={
                "lat": lat, "lon": lon, "format": "jsonv2",
                "zoom": 16, "addressdetails": 1,
            },
            headers={"User-Agent": _NOMINATIM_UA},
            timeout=10.0,
        )
        _LAST_GEOCODE_TS = time.monotonic()
        resp.raise_for_status()
        label = _short_place(resp.json())
        cache[key] = label
        return label
    except Exception as exc:  # noqa: BLE001 - geocoding is enrichment, never fatal
        _log.info("ingest_location: reverse geocode failed for %.4f,%.4f (%s)",
                  lat, lon, exc)
        cache[key] = None
        return None


# ── stay-point clustering ─────────────────────────────────────────────────────

def _cluster_stays(
    points: list[dict], *, radius_m: int, min_dwell_min: int, max_gap_min: int
) -> list[dict]:
    """Greedy stay-point detection over time-sorted fixes.

    A *stay* is a maximal run of consecutive fixes within ``radius_m`` of the
    run's first fix that spans at least ``min_dwell_min``. Fixes that don't
    form a long-enough cluster are treated as transit and dropped. A time gap
    larger than ``max_gap_min`` between consecutive fixes breaks a stay (e.g.
    the phone was off or out of signal)."""
    stays: list[dict] = []
    n = len(points)
    i = 0
    while i < n:
        lat0, lon0 = points[i]["lat"], points[i]["lon"]
        j = i + 1
        while j < n:
            if (points[j]["tst"] - points[j - 1]["tst"]) / 60.0 > max_gap_min:
                break
            if _haversine_m(lat0, lon0, points[j]["lat"], points[j]["lon"]) > radius_m:
                break
            j += 1
        cluster = points[i:j]
        dwell_min = (cluster[-1]["tst"] - cluster[0]["tst"]) / 60.0 if len(cluster) >= 2 else 0.0
        if len(cluster) >= 2 and dwell_min >= min_dwell_min:
            clat = sum(p["lat"] for p in cluster) / len(cluster)
            clon = sum(p["lon"] for p in cluster) / len(cluster)
            stays.append({
                "lat": round(clat, 6),
                "lon": round(clon, 6),
                "arrive": cluster[0]["tst"],
                "depart": cluster[-1]["tst"],
                "dwell_min": int(round(dwell_min)),
                "fixes": len(cluster),
            })
            i = j
        else:
            i += 1  # transit fix — advance one and re-anchor
    return stays


def _place_tags(stays: list[dict]) -> list[str]:
    tags = ["location"]
    for s in stays:
        p = s.get("place")
        if p:
            t = re.sub(r"[^a-z0-9]+", "-", p.split(",")[0].lower()).strip("-")
            if t and t not in tags:
                tags.append(t)
    return tags[:6]


def _route_tags(analysis: dict) -> list[str]:
    tags = ["location", "travel", "owntracks", "route"]
    for anchor in analysis.get("anchors", []):
        place = (anchor.get("place") or "").lower()
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", place):
            if token in {"the", "and", "city", "district", "province", "region"}:
                continue
            if token not in tags:
                tags.append(token)
            if len(tags) >= 8:
                return tags
    return tags


def _fmt_distance_km(metres: float) -> str:
    km = metres / 1000.0
    return f"{km:.0f} km" if km >= 100 else f"{km:.1f} km"


def _dedupe_route_anchors(anchors: list[dict], *, radius_m: int = 800) -> list[dict]:
    kept: list[dict] = []
    for anchor in anchors:
        if any(
            _haversine_m(anchor["lat"], anchor["lon"], k["lat"], k["lon"]) <= radius_m
            and anchor.get("kind") not in {"first", "last"}
            for k in kept
        ):
            continue
        kept.append(anchor)
    return kept


def _select_route_anchors(
    points: list[dict], *, min_move_m: int = 5_000, max_anchors: int = 6
) -> list[dict]:
    """Pick a small chronological set of route anchors from raw fixes.

    The goal is HFL prose, not a track log: first point, large jump boundaries,
    meaningfully moved samples, and final point. Coordinates stay internal and
    are only used for reverse-geocoding labels.
    """
    if not points:
        return []
    selected: list[dict] = [dict(points[0], kind="first")]

    jumps: list[tuple[float, int]] = []
    for i in range(1, len(points)):
        jump_m = _haversine_m(points[i - 1]["lat"], points[i - 1]["lon"], points[i]["lat"], points[i]["lon"])
        if jump_m >= 50_000:
            jumps.append((jump_m, i))
    for _jump_m, i in sorted(jumps, reverse=True)[:2]:
        selected.append(dict(points[i - 1], kind="before-jump"))
        selected.append(dict(points[i], kind="after-jump"))

    last = selected[-1]
    for p in points[1:-1]:
        if _haversine_m(last["lat"], last["lon"], p["lat"], p["lon"]) >= min_move_m:
            selected.append(dict(p, kind="moved-sample"))
            last = p
        if len(selected) >= max_anchors - 1:
            break

    selected.append(dict(points[-1], kind="last"))
    selected.sort(key=lambda p: p["tst"])
    return _dedupe_route_anchors(selected)[:max_anchors]


def _analyze_route_activity(
    activity: dict,
    *,
    min_points: int = 10,
    min_direct_distance_m: int = 20_000,
    min_path_distance_m: int = 30_000,
    min_jump_m: int = 50_000,
    do_geocode: bool = True,
) -> dict[str, Any]:
    """Detect travel-worthy movement from raw OwnTracks fixes.

    Stays are handled elsewhere. This catches travel days where the trace is
    meaningful but too fragmented to form a 15-minute stay-point.
    """
    points = list(activity.get("_points") or [])
    points.sort(key=lambda p: p["tst"])
    if len(points) < min_points:
        return {"travel": False, "reason": "too-few-points", "point_count": len(points)}

    direct_m = _haversine_m(points[0]["lat"], points[0]["lon"], points[-1]["lat"], points[-1]["lon"])
    jumps = [
        _haversine_m(points[i - 1]["lat"], points[i - 1]["lon"], points[i]["lat"], points[i]["lon"])
        for i in range(1, len(points))
    ]
    path_m = sum(jumps)
    max_jump_m = max(jumps) if jumps else 0.0
    travel = (
        direct_m >= min_direct_distance_m
        or path_m >= min_path_distance_m
        or max_jump_m >= min_jump_m
    )
    if not travel:
        return {
            "travel": False,
            "reason": "movement-below-route-threshold",
            "point_count": len(points),
            "direct_distance_m": direct_m,
            "path_distance_m": path_m,
            "max_jump_m": max_jump_m,
        }

    anchors = _select_route_anchors(points)
    if do_geocode and anchors:
        cache: dict = {}
        for anchor in anchors:
            place = _reverse_geocode(anchor["lat"], anchor["lon"], cache=cache)
            if place:
                anchor["place"] = place

    return {
        "travel": True,
        "point_count": len(points),
        "direct_distance_m": direct_m,
        "path_distance_m": path_m,
        "max_jump_m": max_jump_m,
        "anchors": anchors,
    }


def _route_summary_entry(analysis: dict) -> dict[str, Any]:
    """Return deterministic HFL fields for travel days with no stay-points."""
    anchors = analysis.get("anchors") or []
    labelled = [a for a in anchors if a.get("place")]
    start = labelled[0]["place"] if labelled else "the starting area"
    end = labelled[-1]["place"] if labelled else "the ending area"

    route_bits: list[str] = []
    seen: set[str] = set()
    for anchor in anchors:
        label = anchor.get("place")
        if not label or label in seen:
            continue
        seen.add(label)
        route_bits.append(f"{_fmt_clock(anchor['tst'])} — {label}")
    route_text = "; ".join(route_bits[:6]) if route_bits else "route anchors were detected but could not be reverse-geocoded"

    distance_text = _fmt_distance_km(max(
        float(analysis.get("direct_distance_m") or 0),
        float(analysis.get("max_jump_m") or 0),
    ))
    return {
        "skip": False,
        "moment": f"Travelled from {start} to {end}",
        "what_happened": (
            f"OwnTracks recorded {analysis.get('point_count', 0)} GPS fix(es) across a "
            f"travel-heavy day, including a movement span of about {distance_text}. "
            f"Route anchors: {route_text}. No single place crossed the configured "
            "stay-point threshold, but the path itself was story-worthy."
        ),
        "why_it_stayed": (
            "This preserves the shape of a real travel day in HFL instead of reducing "
            "a useful location trace to a generic breadcrumb."
        ),
        "possible_use": "timeline, travel diary, diagnostics",
        "tags": _route_tags(analysis),
        "synthesized": False,
    }


def _location_window(window_days: int, *, today: Optional[date] = None) -> tuple[date, date]:
    """Return the inclusive calendar-day window for a location ingest run."""
    end = today or datetime.now().date()
    days = max(1, int(window_days or 1))
    start = end - timedelta(days=days - 1)
    return start, end


def _resolve_device(
    user: Optional[str], device: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    u = (user or os.environ.get("OWN_TRACKS_DEFAULT_USER", "")).strip() or None
    d = (device or os.environ.get("OWN_TRACKS_DEFAULT_DEVICE", "")).strip() or None
    return u, d


# ── collection ────────────────────────────────────────────────────────────────

def collect_location_activity(
    *,
    since: date,
    until: date,
    user: Optional[str] = None,
    device: Optional[str] = None,
    radius_m: int = 150,
    min_dwell_min: int = 15,
    max_gap_min: int = 90,
    max_points: int = 5000,
    do_geocode: bool = True,
) -> dict[str, Any]:
    """Pull the OwnTracks track for ``[since, until]`` and cluster it into
    reverse-geocoded stay-points.

    Returns:
        {"user","device","point_count","stays":[{place?,lat,lon,arrive,
         depart,dwell_min,fixes}], "stay_count", "window"}.
        When no user/device resolves, returns the same shape with
        ``reason="no-device-configured"`` and zero stays (the caller no-ops).
    """
    u, d = _resolve_device(user, device)
    if not u or not d:
        return {"user": u, "device": d, "point_count": 0, "stays": [],
                "stay_count": 0, "reason": "no-device-configured"}

    from_ts = int(datetime(since.year, since.month, since.day).timestamp())
    to_ts = int(
        (datetime(until.year, until.month, until.day) + timedelta(days=1)).timestamp()
    )

    svc = ApiServiceOwnTracksLocations(OWN_TRACKS_CONFIG)
    result = svc.get_history(user=u, device=d, from_ts=from_ts, to_ts=to_ts)
    rows = (result or {}).get("data", []) if isinstance(result, dict) else []

    points: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        lat, lon, tst = r.get("lat"), r.get("lon"), r.get("tst")
        if lat is None or lon is None or tst is None:
            continue
        try:
            points.append({"lat": float(lat), "lon": float(lon), "tst": int(tst)})
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda p: p["tst"])
    points = points[:max_points]

    stays = _cluster_stays(
        points, radius_m=radius_m, min_dwell_min=min_dwell_min, max_gap_min=max_gap_min
    )

    if do_geocode and stays:
        cache: dict = {}
        for s in stays:
            place = _reverse_geocode(s["lat"], s["lon"], cache=cache)
            if place:
                s["place"] = place

    return {
        "user": u,
        "device": d,
        "point_count": len(points),
        "stays": stays,
        "stay_count": len(stays),
        "window": {"from": from_ts, "to": to_ts},
        # Internal-only raw fixes for deterministic route summarization. HFL
        # prose and normal responses must not expose raw coordinates.
        "_points": points,
    }


# ── point lookup (for geo-tagging other artifacts, e.g. photos) ───────────────

def nearest_fix(
    when: datetime,
    *,
    user: Optional[str] = None,
    device: Optional[str] = None,
    slack_min: int = 120,
) -> Optional[tuple[float, float]]:
    """Return the ``(lat, lon)`` of the OwnTracks fix closest in time to
    ``when``, or ``None``.

    Used to geo-tag artifacts that carry a timestamp but no coordinates of
    their own (a screenshot, an EXIF-stripped photo): match the capture time
    to where the device was. Only fixes within ``slack_min`` of ``when`` count.
    Best-effort — no device configured, Recorder unreachable, or no nearby fix
    all return ``None``.
    """
    u, d = _resolve_device(user, device)
    if not u or not d:
        return None
    target = when.timestamp()
    lo = int(target - slack_min * 60)
    hi = int(target + slack_min * 60)
    try:
        svc = ApiServiceOwnTracksLocations(OWN_TRACKS_CONFIG)
        result = svc.get_history(user=u, device=d, from_ts=lo, to_ts=hi)
    except Exception as exc:  # noqa: BLE001 - geo-tag is best-effort
        _log.info("ingest_location.nearest_fix: recorder unavailable (%s)", exc)
        return None
    rows = (result or {}).get("data", []) if isinstance(result, dict) else []
    best: Optional[tuple[float, float]] = None
    best_dt = slack_min * 60 + 1
    for r in rows:
        if not isinstance(r, dict):
            continue
        lat, lon, tst = r.get("lat"), r.get("lon"), r.get("tst")
        if lat is None or lon is None or tst is None:
            continue
        try:
            delta = abs(int(tst) - target)
        except (TypeError, ValueError):
            continue
        if delta < best_dt:
            best_dt = delta
            best = (float(lat), float(lon))
    return best


# ── distillation ──────────────────────────────────────────────────────────────

def _fmt_clock(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _activity_body(activity: dict) -> str:
    lines: list[str] = []
    for s in activity["stays"]:
        place = s.get("place") or f"{s['lat']:.4f},{s['lon']:.4f}"
        lines.append(
            f"- {_fmt_clock(s['arrive'])}->{_fmt_clock(s['depart'])} "
            f"({s['dwell_min']} min)  {place}"
        )
    return "\n".join(lines)


def _movement_only_entry(activity: dict, *, min_dwell_min: int) -> dict[str, Any]:
    """Return deterministic HFL fields for GPS-active days with no stays.

    This is intentionally non-LLM: the point track proves the day had location
    signal, but without a stable stay-point there is no safe place narrative to
    synthesize. Keep it as an audit/timeline breadcrumb.
    """
    point_count = int(activity.get("point_count") or 0)
    window = activity.get("window") or {}
    start = window.get("from")
    end = window.get("to")
    if start and end:
        window_text = f"between {_fmt_clock(int(start))} and {_fmt_clock(int(end))}"
    else:
        window_text = "during the ingest window"
    return {
        "skip": False,
        "moment": "Recorded movement but no qualifying location stay",
        "what_happened": (
            f"OwnTracks recorded {point_count} GPS fix(es) {window_text}, "
            f"but none formed a stay-point of at least {min_dwell_min} minutes. "
            "The location stream was alive; the day just did not cross the "
            "configured dwell threshold for a place timeline."
        ),
        "why_it_stayed": (
            "This keeps a GPS-active day visible in HFL instead of letting the "
            "location pipeline silently no-op when movement is too brief or fragmented."
        ),
        "possible_use": "timeline, diagnostics",
        "tags": ["location", "movement-only", "owntracks", "no-stays"],
        "synthesized": False,
    }


def distill_location_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected stay-points into HFL entry fields (Haiku, raw fallback)."""
    stays = activity["stays"]
    stay_count = activity["stay_count"]

    def _fallback() -> dict:
        return {
            "skip": False,
            "moment": f"Visited {stay_count} place(s) across the day",
            "what_happened": _activity_body(activity),
            "why_it_stayed": "",
            "possible_use": "timeline",
            "tags": _place_tags(stays),
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = (
        f"Stay-points for the day ({stay_count} place(s), "
        f"{activity['point_count']} fixes), in chronological order:\n\n"
        f"{_activity_body(activity)}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_location: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_location").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_location: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


# ── task ──────────────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def ingest_location_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    user: Optional[str] = None,
    device: Optional[str] = None,
    radius_m: int = 150,
    min_dwell_min: int = 15,
    max_gap_min: int = 90,
    max_points: int = 5000,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's location timeline.

    No device configured, Recorder unreachable, or no fixes in the window → no
    entry, no LLM call. Fixes with no stay-points produce a deterministic
    movement-only entry.
    """
    since, until = _location_window(window_days)

    try:
        activity = collect_location_activity(
            since=since, until=until, user=user, device=device,
            radius_m=radius_m, min_dwell_min=min_dwell_min,
            max_gap_min=max_gap_min, max_points=max_points,
        )
    except Exception as exc:  # noqa: BLE001 - Recorder down must not break beat
        _log.error("ingest_location: OwnTracks Recorder unavailable (%s)", exc)
        return {"skipped": "recorder unavailable", "entries_written": 0,
                "error": str(exc)[:200]}

    if activity.get("reason") == "no-device-configured":
        _log.info("ingest_location: no OwnTracks user/device configured — skip")
        return {"skipped": "no device configured", "entries_written": 0}

    if activity["stay_count"] == 0 and activity["point_count"] == 0:
        _log.info("ingest_location: no stay-points in last %d day(s)", window_days)
        return {"skipped": "no stays", "entries_written": 0,
                "points": activity["point_count"]}

    if activity["stay_count"] == 0:
        route = _analyze_route_activity(activity)
        if route.get("travel"):
            _log.info(
                "ingest_location: %d fix(es) form a travel route; writing route summary",
                activity["point_count"],
            )
            d = _route_summary_entry(route)
            references: list[str] = []
        else:
            _log.info(
                "ingest_location: %d fix(es) but no stay-points; writing movement-only entry",
                activity["point_count"],
            )
            d = _movement_only_entry(activity, min_dwell_min=min_dwell_min)
            references = []
    else:
        d = distill_location_activity(
            activity, synthesize=True, model=model,
            cfg_id=cfg_id__anthropic, max_tokens=900,
        )
        if d.get("skip"):
            _log.info("ingest_location: distilled as skip — %d stays not story-worthy",
                      activity["stay_count"])
            return {"skipped": "distilled-skip", "entries_written": 0,
                    "stay_count": activity["stay_count"]}

        # Provenance: a map pin at the longest-dwell stay (the day's centre of gravity).
        anchor = max(activity["stays"], key=lambda s: s["dwell_min"])
        references = [_osm_link(anchor["lat"], anchor["lon"])]

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"
    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "timeline",
        tags=d.get("tags") or _place_tags(activity["stays"]),
        references=references,
    )
    bytes_written, doc_id = append_entry(
        day_file, entry, source="location", synthesized=d.get("synthesized", False),
    )

    _log.info("ingest_location: entry written (%d stays, %d fixes) -> %s",
              activity["stay_count"], activity["point_count"], day_file)
    return {
        "entries_written": 1,
        "stays": activity["stay_count"],
        "points": activity["point_count"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
        "indexed": doc_id is not None,
    }
