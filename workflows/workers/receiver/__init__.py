# workflows/workers/receiver — HTTP ingress for edge sensor telemetry.
#
# A thin FastAPI app that validates a sensor reading POSTed by an edge device
# (ESP32 over Wi-Fi/LTE) and hands it to the `ingest_sensor_reading` Celery
# task. It holds no business logic — index/threshold/alert all live in the task
# so they are unit-testable without a web server.
#
# Run it on the host or a Pi bridge (both reachable over the tailnet):
#     uvicorn workflows.workers.receiver.app:app --host 0.0.0.0 --port 8770
#
# Full design: docs/info/EDGE-SENSOR-TELEMETRY.md
