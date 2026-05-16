"""
workflows/workers/tasks/broadcast_report_location.py

Cluster-wide GPS location broadcast — every Celery worker that subscribes
to the ``workers_broadcast`` fanout queue reports its current location to
Elasticsearch on each tick.

Routing
-------
The task name starts with ``broadcast_``, which matches the routing rule::

    "workflows.workers.tasks.broadcast_*": {"queue": "workers_broadcast"}

added to ``SPROUT.conf.task_routes`` in ``workflows/config.py``.

Location resolution (device-agnostic cascade)
----------------------------------------------
The resolver tries three methods in order and returns the first non-None fix:

1. **Environment variables** (``WORKER_LAT`` / ``WORKER_LON``) — a static
   coordinate pinned by the operator.  Works on *any* device: Windows, Linux,
   macOS, Android (Termux).  Fastest, zero network.

2. **IP-geolocation** (``ip-api.com``) — free, unauthenticated lookup of the
   worker's public egress IP.  Accurate to city level; sufficient for fleet
   dashboards.  Disabled when ``WORKER_SKIP_IP_GEO=true``.

3. **OwnTracks Recorder REST API** — queries the local/remote Recorder for
   the most-recent GPS fix for the configured user+device.  Requires the
   ``OWN_TRACKS`` block in ``apps_config.yaml`` and the Recorder to be
   reachable from the worker.

If all three fail, a ``GeoPoint(source="unavailable")`` is stored so the ES
document is always complete — the absence of coordinates can be queried and
alerted on without missing documents.

ES document
-----------
Each execution writes one document to ``harqis-worker-locations`` (override
via the ``WORKER_LOCATIONS_INDEX`` env var).  The document shape is defined
by ``DtoWorkerLocation`` in ``workflows/workers/dto/worker_location.py``.

Idempotency
-----------
The document ID is ``<machine_name>_latest`` — each broadcast *overwrites*
the previous entry for this machine, so Kibana always shows the freshest fix
per node without unbounded index growth.  Historical tracking requires a
separate time-series write strategy (e.g. append-only with ``update_interval
= MINUTE``).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from core.apps.sprout.app.celery import SPROUT
from workflows.workers.dto.worker_location import (
    DtoWorkerLocation,
    GeoPoint,
    WORKER_LOCATIONS_INDEX,
)

_log = logging.getLogger(__name__)

# ── Module-level last-known fix cache (per-worker-process) ───────────────────
# Persisted only for the lifetime of the worker process; resets on restart.
# Lets the document carry a meaningful `last_location` (previous fix) so
# movement can be detected in Kibana without a second query.
_last_location_cache: Optional[GeoPoint] = None


# ─────────────────────────────────────────────────────────────────────────────
# Location resolvers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_via_env() -> Optional[GeoPoint]:
    """Return a GeoPoint from ``WORKER_LAT`` / ``WORKER_LON`` env vars.

    This is the simplest and most portable resolver — set the two variables
    on any device (Windows, Linux, macOS, Android/Termux) to pin a static
    coordinate.  Useful for workers installed at fixed premises (office,
    server rack, home).

    Returns ``None`` when either variable is absent or non-numeric.
    """
    raw_lat = os.environ.get("WORKER_LAT")
    raw_lon = os.environ.get("WORKER_LON")
    if not raw_lat or not raw_lon:
        return None
    try:
        return GeoPoint(
            lat=float(raw_lat),
            lon=float(raw_lon),
            source="env",
        )
    except (ValueError, TypeError):
        return None


def _resolve_via_ip_geolocation() -> Optional[GeoPoint]:
    """Return an approximate GeoPoint from the worker's public egress IP.

    Uses the free ``ip-api.com`` JSON endpoint — no API key, no account.
    Accurate to city level; good enough for fleet dashboards.

    Set ``WORKER_SKIP_IP_GEO=true`` to skip this resolver entirely
    (useful for workers on private networks or when privacy is a concern).

    Returns ``None`` on network error, API failure, or ``status != "success"``.
    """
    if os.environ.get("WORKER_SKIP_IP_GEO", "").lower() == "true":
        return None

    try:
        resp = requests.get(
            "http://ip-api.com/json/",
            timeout=5,
            params={"fields": "status,lat,lon,city,regionName,country,isp"},
        )
        data = resp.json()
        if data.get("status") != "success":
            _log.debug("ip-api returned non-success status: %s", data.get("message"))
            return None
        return GeoPoint(
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            source="ip_geolocation",
        )
    except Exception as exc:
        _log.debug("IP-geolocation lookup failed: %s", exc)
        return None


def _resolve_via_owntracks(owntracks_cfg_id: str = "OWN_TRACKS") -> Optional[GeoPoint]:
    """Return the latest OwnTracks fix for the configured user/device.

    Reads the ``OWN_TRACKS`` block (or the value of ``owntracks_cfg_id``) from
    ``apps_config.yaml`` and queries the Recorder's ``/api/0/last`` endpoint.
    Uses ``default_user`` / ``default_device`` from ``app_data`` when the
    caller doesn't supply them.

    Returns ``None`` when the Recorder is unreachable, the config block is
    missing, or no fix has been recorded yet.
    """
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.own_tracks.references.web.api.locations import (
            ApiServiceOwnTracksLocations,
        )
    except Exception as exc:
        _log.debug("OwnTracks import failed: %s", exc)
        return None

    try:
        cfg = CONFIG_MANAGER.get(owntracks_cfg_id)
        svc = ApiServiceOwnTracksLocations(cfg)

        # Use configured defaults so the task works without explicit args.
        user = cfg.app_data.get("default_user")
        device = cfg.app_data.get("default_device")

        locations = svc.get_last(user=user, device=device) or []
        if not locations:
            return None

        # Pick the newest fix by `tst` (Unix epoch seconds).
        def _tst(loc: dict) -> int:
            try:
                return int(loc.get("tst") or 0)
            except Exception:
                return 0

        best = sorted(locations, key=_tst, reverse=True)[0]
        lat = best.get("lat")
        lon = best.get("lon")
        if lat is None or lon is None:
            return None

        return GeoPoint(
            lat=float(lat),
            lon=float(lon),
            accuracy=float(best["acc"]) if best.get("acc") is not None else None,
            altitude=float(best["alt"]) if best.get("alt") is not None else None,
            speed_kmh=float(best["vel"]) if best.get("vel") is not None else None,
            source="owntracks",
        )
    except Exception as exc:
        _log.debug("OwnTracks resolver failed: %s", exc)
        return None


def _resolve_location(owntracks_cfg_id: str = "OWN_TRACKS") -> GeoPoint:
    """Run the resolver cascade and return the best available fix.

    Priority:
      1. Environment variables (``WORKER_LAT`` / ``WORKER_LON``)
      2. IP-geolocation (``ip-api.com``)
      3. OwnTracks Recorder REST API

    Always returns a ``GeoPoint`` — callers never need a None check.
    When all resolvers fail, ``source="unavailable"`` signals the absence.
    """
    fix = _resolve_via_env()
    if fix is not None:
        return fix

    fix = _resolve_via_ip_geolocation()
    if fix is not None:
        return fix

    fix = _resolve_via_owntracks(owntracks_cfg_id)
    if fix is not None:
        return fix

    return GeoPoint(source="unavailable")


# ─────────────────────────────────────────────────────────────────────────────
# ES persistence helper
# ─────────────────────────────────────────────────────────────────────────────

def _post_to_es(doc: DtoWorkerLocation) -> bool:
    """Index ``doc`` into Elasticsearch.

    Uses ``_doc/<machine_name>_latest`` as the document ID so each worker
    always overwrites its own previous entry (last-write-wins per node).

    Returns ``True`` on success, ``False`` on any error (logging only —
    the task must never fail because of an ES outage).
    """
    try:
        from core.apps.es_logging.app.elasticsearch import post as es_post
        es_post(
            json_dump=doc.to_dict(),
            index_name=WORKER_LOCATIONS_INDEX,
            location_key="{0}_latest".format(doc.machine_name),
            use_interval_map=False,
        )
        return True
    except Exception as exc:
        _log.warning(
            "broadcast_report_location: ES write failed for %s — %s",
            doc.machine_name,
            exc,
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Broadcast task
# ─────────────────────────────────────────────────────────────────────────────

@SPROUT.task(name="workflows.workers.tasks.broadcast_report_location")
def broadcast_report_location(**kwargs) -> dict:
    """Report this worker's GPS coordinates to Elasticsearch.

    Runs on *every* Celery worker subscribed to ``workers_broadcast`` simultaneously.
    The task is safe to run concurrently across different machines because each
    worker writes to its own document ID (``<machine_name>_latest``).

    Kwargs (all optional — passed through from beat schedule or ad-hoc calls):
        owntracks_cfg_id: Config key for the OwnTracks Recorder.
                          Defaults to ``"OWN_TRACKS"``.

    Returns a payload dict suitable for logging by Flower / Elasticsearch:
        task            : task name
        machine_name    : hostname of this worker
        worker_name     : Celery worker process name (if resolvable)
        platform_os     : normalised OS family (windows / linux / darwin / android)
        platform_detail : full platform string
        time_sent       : ISO-8601 UTC timestamp
        location_source : how the fix was obtained (env / ip_geolocation / owntracks / unavailable)
        new_location    : GeoPoint dict (lat/lon/accuracy/…) or None
        last_location   : previous GeoPoint dict, or None (first run)
        owntracks_user  : OwnTracks username, if known
        owntracks_device: OwnTracks device name, if known
        es_indexed      : True if the ES write succeeded
        index           : the ES index name that was targeted
    """
    global _last_location_cache  # noqa: PLW0603

    owntracks_cfg_id = kwargs.get("owntracks_cfg_id", "OWN_TRACKS")

    # ── Resolve current location ─────────────────────────────────────────────
    new_location = _resolve_location(owntracks_cfg_id=owntracks_cfg_id)
    last_location = _last_location_cache  # may be None on first run

    # ── Resolve OwnTracks identity (user/device) from config, best-effort ────
    owntracks_user = ""
    owntracks_device = ""
    try:
        from apps.apps_config import CONFIG_MANAGER
        cfg = CONFIG_MANAGER.get(owntracks_cfg_id)
        owntracks_user = cfg.app_data.get("default_user", "") or ""
        owntracks_device = cfg.app_data.get("default_device", "") or ""
    except Exception:
        pass  # config missing or Recorder not configured on this worker

    # ── Resolve Celery worker name, best-effort ──────────────────────────────
    worker_name = ""
    try:
        from celery._state import get_current_worker_task
        t = get_current_worker_task()
        if t and hasattr(t, "request"):
            worker_name = t.request.hostname or ""
    except Exception:
        pass

    # ── Build and persist document ───────────────────────────────────────────
    doc = DtoWorkerLocation.build(
        worker_name=worker_name,
        new_location=new_location,
        last_location=last_location,
        owntracks_user=owntracks_user,
        owntracks_device=owntracks_device,
    )

    es_indexed = _post_to_es(doc)

    # Cache the fix for the *next* invocation so `last_location` is populated.
    if new_location.is_valid():
        _last_location_cache = new_location

    payload = {
        "task":             "broadcast_report_location",
        "machine_name":     doc.machine_name,
        "worker_name":      doc.worker_name,
        "platform_os":      doc.platform_os,
        "platform_detail":  doc.platform_detail,
        "time_sent":        doc.time_sent,
        "location_source":  new_location.source,
        "new_location":     new_location.to_dict(),
        "last_location":    last_location.to_dict() if last_location else None,
        "owntracks_user":   doc.owntracks_user,
        "owntracks_device": doc.owntracks_device,
        "task_name":        doc.task_name,
        "es_indexed":       es_indexed,
        "index":            WORKER_LOCATIONS_INDEX,
    }

    _log.info(
        "[workers_broadcast] report_location on %s — source=%s valid=%s es=%s",
        doc.machine_name,
        new_location.source,
        new_location.is_valid(),
        es_indexed,
    )

    return payload
