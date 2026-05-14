"""
workflows/workers/dto/worker_location.py

Elasticsearch document shape for worker location reports.

One document is emitted per broadcast execution — i.e. once per worker
that receives the `broadcast_report_location` task.  The document captures:

  - identity   : who this worker is (hostname, platform/OS, celery worker name)
  - timing     : when the report was generated + the ES ingestion timestamp
  - location   : coordinates from OwnTracks (if reachable), else None
  - movement   : last known location ↔ new location for change detection

The index is intentionally separate from `harqis-elastic-logging` so
location history can be queried, visualised in Kibana, and retained/purged
independently of operational logs.

Index: ``harqis-worker-locations``  (override via env ``WORKER_LOCATIONS_INDEX``)
"""
from __future__ import annotations

import os
import platform
import socket
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

# Allow the index name to be overridden per-environment without code changes.
WORKER_LOCATIONS_INDEX: str = os.environ.get(
    "WORKER_LOCATIONS_INDEX", "harqis-worker-locations"
)


@dataclass
class GeoPoint:
    """A single GPS fix.

    Attributes:
        lat:       Latitude in decimal degrees.
        lon:       Longitude in decimal degrees.
        accuracy:  Horizontal accuracy radius in metres (None if unknown).
        altitude:  Altitude in metres above sea level (None if unknown).
        speed_kmh: Ground speed in km/h (None if unknown).
        source:    How the fix was obtained, e.g. ``"owntracks"``, ``"ip"``,
                   ``"manual"``, ``"unavailable"``.
    """

    lat: Optional[float] = None
    lon: Optional[float] = None
    accuracy: Optional[float] = None
    altitude: Optional[float] = None
    speed_kmh: Optional[float] = None
    source: str = "unavailable"

    def is_valid(self) -> bool:
        """True when coordinates are present and within sane bounds."""
        return (
            self.lat is not None
            and self.lon is not None
            and -90 <= self.lat <= 90
            and -180 <= self.lon <= 180
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DtoWorkerLocation:
    """One worker-location telemetry document.

    Designed to be serialised straight to JSON and indexed into ES via
    ``core.apps.es_logging.app.elasticsearch.post``.  All fields have safe
    defaults so callers can build a minimal document without filling every
    attribute.

    Attributes:
        # — Identity —
        machine_name:    ``socket.gethostname()`` on the reporting machine.
        worker_name:     Celery worker process name
                         (``celery@<hostname>`` or the ``--hostname`` override).
        platform_os:     OS family: ``"windows"``, ``"linux"``, ``"darwin"``,
                         ``"android"``, or whatever ``platform.system()`` returns.
                         Normalised to lowercase so queries work uniformly across
                         Windows, Linux, macOS, Android (Termux), etc.
        platform_detail: Free-form OS detail — ``platform.platform()`` output,
                         e.g. ``"macOS-14.4-arm64-arm-64bit"``.
                         Android workers running under Termux report
                         ``"Linux-..."`` here, which is why ``platform_os``
                         has a separate normalised field.

        # — Timing —
        time_sent: ISO-8601 UTC timestamp when *this worker* generated the
                   document.  Set automatically if left empty.
        date:      Same as ``time_sent`` — kept for compatibility with the
                   ES logging pipeline that uses ``date`` as the sort key.

        # — Location —
        new_location:  Current GPS fix (may be a null fix if OwnTracks is
                       unreachable or not configured for this device).
        last_location: Previous fix from the most recent successful broadcast
                       on this machine.  ``None`` on first report.

        # — Metadata —
        owntracks_user:   OwnTracks username associated with this device, if
                          known (from ``apps_config.yaml → OWN_TRACKS``).
        owntracks_device: OwnTracks device name, if known.
        task_name:        The Celery task that produced this document.
        extra:            Free-form dict for callers to attach arbitrary context
                          (e.g. ``{"battery": 87, "connection": "wifi"}``).
    """

    # — Identity —
    machine_name: str = field(default_factory=socket.gethostname)
    worker_name: str = ""
    # Normalised OS family — lowercase, works uniformly for all device types:
    # windows, linux, darwin, android (Termux reports "linux" from
    # platform.system(); callers may override with "android" if desired).
    platform_os: str = field(default_factory=lambda: platform.system().lower())
    platform_detail: str = field(default_factory=platform.platform)

    # — Timing —
    time_sent: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # — Location —
    new_location: Optional[GeoPoint] = None
    last_location: Optional[GeoPoint] = None

    # — Metadata —
    owntracks_user: str = ""
    owntracks_device: str = ""
    task_name: str = "broadcast_report_location"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON indexing into ES."""
        d = {
            "machine_name":    self.machine_name,
            "worker_name":     self.worker_name,
            "platform_os":     self.platform_os,
            "platform_detail": self.platform_detail,
            "time_sent":       self.time_sent,
            "date":            self.date,
            "new_location":    self.new_location.to_dict() if self.new_location else None,
            "last_location":   self.last_location.to_dict() if self.last_location else None,
            "owntracks_user":  self.owntracks_user,
            "owntracks_device": self.owntracks_device,
            "task_name":       self.task_name,
            "extra":           self.extra,
        }
        return d

    @classmethod
    def build(
        cls,
        *,
        worker_name: str = "",
        new_location: Optional[GeoPoint] = None,
        last_location: Optional[GeoPoint] = None,
        owntracks_user: str = "",
        owntracks_device: str = "",
        extra: Optional[dict] = None,
    ) -> "DtoWorkerLocation":
        """Convenience factory that auto-populates identity + timing fields."""
        now_iso = datetime.now(timezone.utc).isoformat()
        return cls(
            machine_name=socket.gethostname(),
            worker_name=worker_name,
            platform_os=platform.system().lower(),
            platform_detail=platform.platform(),
            time_sent=now_iso,
            date=now_iso,
            new_location=new_location,
            last_location=last_location,
            owntracks_user=owntracks_user,
            owntracks_device=owntracks_device,
            extra=extra or {},
        )
