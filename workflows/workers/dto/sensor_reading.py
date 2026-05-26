"""
workflows/workers/dto/sensor_reading.py

Elasticsearch document shape for edge sensor telemetry.

One document is emitted per reading received from an edge device (ESP32, Pi
sensor HAT, …) over the HTTP telemetry receiver.  Unlike worker-location
documents (which use a ``<machine>_latest`` last-write-wins ID), sensor
readings are **append-only time series** — every reading is its own document so
history can be charted in Kibana and alerted on.

Index: ``harqis-sensor-telemetry``  (override via env ``SENSOR_TELEMETRY_INDEX``)

Threshold config
----------------
``ThresholdRule`` describes the alerting bounds for a single metric.  A reading
breaches when ``value < min`` or ``value > max`` (either bound may be ``None``
to leave that side unbounded).  Rules are supplied to the ingest task as a
``{metric: {"min": .., "max": .., "unit": ".."}}`` mapping — see
``ingest_sensor_reading`` for how they are sourced (task kwarg → env JSON).
"""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

# Allow the index name to be overridden per-environment without code changes.
SENSOR_TELEMETRY_INDEX: str = os.environ.get(
    "SENSOR_TELEMETRY_INDEX", "harqis-sensor-telemetry"
)


@dataclass
class DtoSensorReading:
    """One sensor reading telemetry document.

    Serialises straight to JSON for indexing into ES via
    ``core.apps.es_logging.app.elasticsearch.post``.  All fields have safe
    defaults so a minimal reading (``device_id``/``metric``/``value``) is enough.

    Attributes:
        device_id:    Stable per-device identifier (e.g. ``"esp32-garage"``).
        metric:       What was measured (e.g. ``"temperature"``, ``"humidity"``,
                      ``"co2"``, ``"power_w"``).
        value:        The measured value.
        unit:         Unit of measure (e.g. ``"C"``, ``"%"``, ``"ppm"``, ``"W"``).
        location:     Free-text placement of the device (e.g. ``"garage"``).
        device_ts:    ISO-8601 UTC timestamp the device captured the reading.
                      Defaults to ingest time when the device omits it.
        date:         ES sort key — same value as ``device_ts``.
        ingested_by:  Hostname of the bridge/host that received the reading.
        breached:     True when the value violated a supplied threshold rule.
        threshold:    The rule that was evaluated (``min``/``max``/``unit``), or
                      ``None`` when no rule applied.
        extra:        Free-form dict for arbitrary device context
                      (e.g. ``{"battery": 87, "rssi": -61}``).
    """

    device_id: str = ""
    metric: str = ""
    value: Optional[float] = None
    unit: str = ""
    location: str = ""

    device_ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    ingested_by: str = field(default_factory=socket.gethostname)
    breached: bool = False
    threshold: Optional[dict] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON indexing into ES."""
        return asdict(self)

    @classmethod
    def build(
        cls,
        *,
        device_id: str,
        metric: str,
        value: Optional[float],
        unit: str = "",
        location: str = "",
        device_ts: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> "DtoSensorReading":
        """Factory that auto-populates ingest-side fields (timestamps, host).

        ``device_ts`` is preserved when the device supplies it (so the time
        series reflects capture time, not ingest time); otherwise it falls back
        to now.  ``date`` always mirrors ``device_ts`` for the ES sort key.
        """
        ts = device_ts or datetime.now(timezone.utc).isoformat()
        return cls(
            device_id=device_id,
            metric=metric,
            value=value,
            unit=unit,
            location=location,
            device_ts=ts,
            date=ts,
            ingested_by=socket.gethostname(),
            extra=extra or {},
        )


def evaluate_threshold(value: Optional[float], rule: Optional[dict]) -> bool:
    """Return True when ``value`` breaches ``rule``.

    A rule is ``{"min": <float|None>, "max": <float|None>, ...}``.  A breach is
    ``value < min`` or ``value > max``.  Returns False when there is no rule, no
    value, or the value is non-numeric — alerting must never raise.
    """
    if rule is None or value is None:
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    lo = rule.get("min")
    hi = rule.get("max")
    if lo is not None and v < float(lo):
        return True
    if hi is not None and v > float(hi):
        return True
    return False
