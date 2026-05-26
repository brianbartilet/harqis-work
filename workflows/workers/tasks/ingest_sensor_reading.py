"""
workflows/workers/tasks/ingest_sensor_reading.py

Ingest one edge-sensor reading into Elasticsearch, evaluate it against a
threshold rule, and fire a Discord alert on breach.

Pipeline
--------
    ESP32 sensor ──HTTP POST──▶ receiver (workflows/workers/receiver/app.py)
                                      │  ingest_sensor_reading.delay(...)
                                      ▼
                          ┌───────────────────────────┐
                          │ ingest_sensor_reading      │
                          │  1. build DtoSensorReading │
                          │  2. evaluate threshold     │
                          │  3. index to ES (append)   │
                          │  4. Discord alert on breach│
                          └───────────────────────────┘

This is a normal direct task (NOT a ``broadcast_*`` fanout) — it runs once, on
whichever worker on the ``default`` queue picks it up.  The HUD widget
(``workflows/hud/tasks/hud_sensors.py``) reads the same index back for display.

Thresholds
----------
Resolved in this order (first non-empty wins):
  1. the ``thresholds`` task kwarg (a ``{metric: rule}`` dict)
  2. the ``SENSOR_THRESHOLDS`` env var (JSON of the same shape)
A rule is ``{"min": <float|None>, "max": <float|None>, "unit": "<str>"}``.

Discord alert
-------------
Credentials are read from (first present wins):
  1. env ``DISCORD_ALERT_WEBHOOK_ID`` / ``DISCORD_ALERT_WEBHOOK_TOKEN``
  2. the ``DISCORD`` config block's ``app_data.alert_webhook_id`` / ``…_token``
When neither is configured the alert is skipped (logged at debug) — a breach is
still recorded in ES via the ``breached`` flag, so nothing is lost.

Resilience
----------
ES and Discord failures are logged and swallowed — the task never raises on an
outage of a downstream system (mirrors ``broadcast_report_location``).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from core.apps.sprout.app.celery import SPROUT
from workflows.workers.dto.sensor_reading import (
    DtoSensorReading,
    SENSOR_TELEMETRY_INDEX,
    evaluate_threshold,
)

_log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Threshold resolution
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_thresholds(thresholds: Optional[dict]) -> dict:
    """Return the active ``{metric: rule}`` map (kwarg → env JSON → {})."""
    if thresholds:
        return thresholds
    raw = os.environ.get("SENSOR_THRESHOLDS")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        _log.debug("SENSOR_THRESHOLDS is not valid JSON — ignoring")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# ES persistence
# ─────────────────────────────────────────────────────────────────────────────

def _post_to_es(doc: DtoSensorReading) -> bool:
    """Append ``doc`` to the sensor telemetry index (one doc per reading).

    Uses a unique ``location_key`` (``<device>_<metric>_<ts>``) so readings
    accumulate as a time series instead of overwriting each other.

    Returns ``True`` on success, ``False`` on any error (logging only — an ES
    outage must never fail the task).
    """
    try:
        from core.apps.es_logging.app.elasticsearch import post as es_post
        key = "{0}_{1}_{2}".format(doc.device_id, doc.metric, doc.device_ts)
        es_post(
            json_dump=doc.to_dict(),
            index_name=SENSOR_TELEMETRY_INDEX,
            location_key=key,
            use_interval_map=False,
        )
        return True
    except Exception as exc:
        _log.warning(
            "ingest_sensor_reading: ES write failed for %s/%s — %s",
            doc.device_id, doc.metric, exc,
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Discord alerting
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_discord_webhook() -> Optional[tuple]:
    """Return ``(webhook_id, webhook_token)`` or ``None`` when unconfigured."""
    wid = os.environ.get("DISCORD_ALERT_WEBHOOK_ID")
    wtok = os.environ.get("DISCORD_ALERT_WEBHOOK_TOKEN")
    if wid and wtok:
        return wid, wtok
    try:
        from apps.discord.config import CONFIG
        wid = CONFIG.app_data.get("alert_webhook_id")
        wtok = CONFIG.app_data.get("alert_webhook_token")
        if wid and wtok:
            return wid, wtok
    except Exception as exc:  # config block absent / not loaded
        _log.debug("Discord config unavailable for alert: %s", exc)
    return None


def _maybe_alert_discord(doc: DtoSensorReading) -> bool:
    """Post a Discord embed when the reading breached its threshold.

    Returns ``True`` if an alert was sent, ``False`` otherwise (not breached,
    unconfigured, or send failed — all non-fatal).
    """
    if not doc.breached:
        return False
    creds = _resolve_discord_webhook()
    if creds is None:
        _log.debug("threshold breached but no Discord webhook configured — skipping alert")
        return False
    webhook_id, webhook_token = creds
    try:
        from apps.discord.config import CONFIG
        from apps.discord.references.web.api.webhooks import ApiServiceDiscordWebhooks

        rule = doc.threshold or {}
        bounds = "min={0} max={1}".format(rule.get("min"), rule.get("max"))
        where = " @ {0}".format(doc.location) if doc.location else ""
        embed = {
            "title": "⚠️ Sensor threshold breach: {0}".format(doc.metric),
            "description": (
                "**{device}**{where}\n"
                "`{metric}` = **{value} {unit}**  (allowed {bounds})\n"
                "captured {ts}"
            ).format(
                device=doc.device_id, where=where, metric=doc.metric,
                value=doc.value, unit=doc.unit, bounds=bounds, ts=doc.device_ts,
            ),
            "color": 0xE74C3C,  # red
        }
        ApiServiceDiscordWebhooks(CONFIG).execute_webhook(
            webhook_id=webhook_id,
            webhook_token=webhook_token,
            username="harqis-sensors",
            embeds=[embed],
        )
        return True
    except Exception as exc:
        _log.warning("ingest_sensor_reading: Discord alert failed — %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Ingest task
# ─────────────────────────────────────────────────────────────────────────────

@SPROUT.task(name="workflows.workers.tasks.ingest_sensor_reading")
def ingest_sensor_reading(**kwargs) -> dict:
    """Index one sensor reading and alert on threshold breach.

    Kwargs (the reading + options — dispatched from the HTTP receiver):
        device_id:  Stable device identifier (required).
        metric:     Measured metric name (required).
        value:      Measured value (required, numeric).
        unit:       Unit of measure (optional).
        location:   Free-text placement (optional).
        device_ts:  ISO-8601 UTC capture time (optional; defaults to ingest time).
        extra:      Arbitrary device context dict (optional).
        thresholds: ``{metric: rule}`` map; overrides the SENSOR_THRESHOLDS env.

    Returns a payload dict for Flower / logging with the indexed/alerted flags.
    """
    device_id = kwargs.get("device_id", "")
    metric = kwargs.get("metric", "")
    value = kwargs.get("value")

    doc = DtoSensorReading.build(
        device_id=device_id,
        metric=metric,
        value=value,
        unit=kwargs.get("unit", ""),
        location=kwargs.get("location", ""),
        device_ts=kwargs.get("device_ts"),
        extra=kwargs.get("extra") or {},
    )

    # ── Threshold evaluation ─────────────────────────────────────────────────
    thresholds = _resolve_thresholds(kwargs.get("thresholds"))
    rule = thresholds.get(metric)
    doc.threshold = rule
    doc.breached = evaluate_threshold(value, rule)

    # ── Persist + alert ──────────────────────────────────────────────────────
    es_indexed = _post_to_es(doc)
    alerted = _maybe_alert_discord(doc)

    payload = {
        "task":        "ingest_sensor_reading",
        "device_id":   doc.device_id,
        "metric":      doc.metric,
        "value":       doc.value,
        "unit":        doc.unit,
        "location":    doc.location,
        "device_ts":   doc.device_ts,
        "breached":    doc.breached,
        "es_indexed":  es_indexed,
        "alerted":     alerted,
        "index":       SENSOR_TELEMETRY_INDEX,
    }
    _log.info(
        "[ingest_sensor_reading] %s/%s=%s%s breached=%s es=%s alert=%s",
        doc.device_id, doc.metric, doc.value, doc.unit,
        doc.breached, es_indexed, alerted,
    )
    return payload
