"""
workflows/workers/receiver/app.py

FastAPI receiver for edge sensor telemetry.

An ESP32 (or any device) POSTs a JSON reading to ``/telemetry``; the receiver
validates it and dispatches the ``ingest_sensor_reading`` Celery task, which
does the ES write + threshold/alert work. The HTTP layer stays deliberately
thin so the ingest logic is testable without a web server.

Endpoints
---------
    POST /telemetry   → 202 Accepted, dispatches ingest_sensor_reading.delay(...)
    GET  /health      → 200 {"status": "ok"}

Auth (optional)
---------------
If ``SENSOR_RECEIVER_TOKEN`` is set, every ``/telemetry`` request must carry a
matching ``Authorization: Bearer <token>`` header. Unset → open (suitable only
behind the tailnet / a trusted LAN).

Run
---
    uvicorn workflows.workers.receiver.app:app --host 0.0.0.0 --port 8770
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

app = FastAPI(title="harqis-work sensor telemetry receiver", version="1.0.0")


class SensorReadingIn(BaseModel):
    """Inbound reading payload. ``device_id``/``metric``/``value`` are required."""
    device_id: str = Field(..., min_length=1, description="Stable device id, e.g. esp32-garage")
    metric: str = Field(..., min_length=1, description="Measured metric, e.g. temperature")
    value: float = Field(..., description="Measured value")
    unit: str = Field("", description="Unit of measure, e.g. C / % / ppm / W")
    location: str = Field("", description="Free-text placement, e.g. garage")
    device_ts: Optional[str] = Field(None, description="ISO-8601 UTC capture time")
    extra: dict = Field(default_factory=dict, description="Arbitrary device context")


def _check_auth(authorization: Optional[str]) -> None:
    """Enforce the bearer token when SENSOR_RECEIVER_TOKEN is configured."""
    expected = os.environ.get("SENSOR_RECEIVER_TOKEN")
    if not expected:
        return  # auth disabled
    if authorization != "Bearer {0}".format(expected):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


@app.get("/health")
def health() -> dict:
    """Liveness probe — no auth."""
    return {"status": "ok"}


@app.post("/telemetry", status_code=202)
def telemetry(reading: SensorReadingIn, authorization: Optional[str] = Header(None)) -> dict:
    """Validate a reading and dispatch it to the ingest task.

    Returns 202 immediately; the actual ES write + alert happen asynchronously
    in the Celery worker. Validation failures are surfaced by FastAPI as 422.
    """
    _check_auth(authorization)

    # Imported lazily so the module imports without a broker (e.g. in tests).
    from workflows.workers.tasks.ingest_sensor_reading import ingest_sensor_reading

    ingest_sensor_reading.delay(**reading.model_dump())
    _log.info("queued reading %s/%s=%s", reading.device_id, reading.metric, reading.value)
    return {"status": "accepted", "device_id": reading.device_id, "metric": reading.metric}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.environ.get("SENSOR_RECEIVER_PORT", "8770"))
    uvicorn.run(app, host="0.0.0.0", port=port)
