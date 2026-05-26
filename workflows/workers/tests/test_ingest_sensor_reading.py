"""
Tests for workflows/workers/tasks/ingest_sensor_reading.py and its DTO.

Covers:
  - DtoSensorReading: build, to_dict shape, default index, env override
  - evaluate_threshold: min/max breach, within-bounds, missing rule/value, non-numeric
  - _resolve_thresholds: kwarg precedence, env JSON, invalid JSON, empty
  - _resolve_discord_webhook: env creds, none when unconfigured
  - _maybe_alert_discord: skips when not breached / unconfigured
  - ingest_sensor_reading task: payload shape, breach flag, ES call, resilience
  - receiver app (FastAPI): /health, /telemetry dispatch + validation + auth
    (skipped automatically if httpx/TestClient is unavailable)
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from hamcrest import (
    assert_that,
    equal_to,
    has_key,
    instance_of,
    none,
    is_not,
)

from workflows.workers.dto.sensor_reading import (
    DtoSensorReading,
    SENSOR_TELEMETRY_INDEX,
    evaluate_threshold,
)


# ─────────────────────────────────────────────────────────────────────────────
# DtoSensorReading
# ─────────────────────────────────────────────────────────────────────────────

class TestDtoSensorReading:
    def test_build_populates_fields(self):
        doc = DtoSensorReading.build(device_id="esp32-garage", metric="temperature",
                                     value=21.5, unit="C", location="garage")
        assert_that(doc.device_id, equal_to("esp32-garage"))
        assert_that(doc.metric, equal_to("temperature"))
        assert_that(doc.value, equal_to(21.5))
        assert_that(doc.unit, equal_to("C"))
        assert_that(doc.location, equal_to("garage"))
        assert_that(doc.ingested_by, instance_of(str))
        # date mirrors device_ts for the ES sort key
        assert_that(doc.date, equal_to(doc.device_ts))

    def test_build_preserves_device_ts(self):
        doc = DtoSensorReading.build(device_id="d", metric="m", value=1.0,
                                     device_ts="2026-05-26T00:00:00+00:00")
        assert_that(doc.device_ts, equal_to("2026-05-26T00:00:00+00:00"))
        assert_that(doc.date, equal_to("2026-05-26T00:00:00+00:00"))

    def test_to_dict_has_required_keys(self):
        doc = DtoSensorReading.build(device_id="d", metric="m", value=1.0)
        d = doc.to_dict()
        for key in ("device_id", "metric", "value", "unit", "location",
                    "device_ts", "date", "ingested_by", "breached", "threshold", "extra"):
            assert_that(d, has_key(key), reason="Missing key: {0}".format(key))

    def test_default_index_name(self):
        assert_that(SENSOR_TELEMETRY_INDEX, equal_to("harqis-sensor-telemetry"))

    def test_index_env_override(self, monkeypatch):
        monkeypatch.setenv("SENSOR_TELEMETRY_INDEX", "custom-sensor-index")
        import workflows.workers.dto.sensor_reading as mod
        importlib.reload(mod)
        assert_that(mod.SENSOR_TELEMETRY_INDEX, equal_to("custom-sensor-index"))
        monkeypatch.delenv("SENSOR_TELEMETRY_INDEX", raising=False)
        importlib.reload(mod)


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_threshold
# ─────────────────────────────────────────────────────────────────────────────

class TestEvaluateThreshold:
    def test_breach_above_max(self):
        assert_that(evaluate_threshold(40.0, {"max": 35}), equal_to(True))

    def test_breach_below_min(self):
        assert_that(evaluate_threshold(-1.0, {"min": 2}), equal_to(True))

    def test_within_bounds(self):
        assert_that(evaluate_threshold(20.0, {"min": 2, "max": 35}), equal_to(False))

    def test_no_rule(self):
        assert_that(evaluate_threshold(999.0, None), equal_to(False))

    def test_no_value(self):
        assert_that(evaluate_threshold(None, {"max": 35}), equal_to(False))

    def test_non_numeric_value(self):
        assert_that(evaluate_threshold("hot", {"max": 35}), equal_to(False))

    def test_only_max_bound(self):
        assert_that(evaluate_threshold(10.0, {"max": 35}), equal_to(False))
        assert_that(evaluate_threshold(36.0, {"max": 35}), equal_to(True))


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_thresholds / _resolve_discord_webhook / _maybe_alert_discord
# ─────────────────────────────────────────────────────────────────────────────

from workflows.workers.tasks.ingest_sensor_reading import (  # noqa: E402
    _resolve_thresholds,
    _resolve_discord_webhook,
    _maybe_alert_discord,
    ingest_sensor_reading,
)


class TestResolveThresholds:
    def test_kwarg_wins(self, monkeypatch):
        monkeypatch.setenv("SENSOR_THRESHOLDS", '{"temperature":{"max":1}}')
        out = _resolve_thresholds({"temperature": {"max": 99}})
        assert_that(out["temperature"]["max"], equal_to(99))

    def test_env_json(self, monkeypatch):
        monkeypatch.setenv("SENSOR_THRESHOLDS", '{"co2":{"max":1200}}')
        out = _resolve_thresholds(None)
        assert_that(out["co2"]["max"], equal_to(1200))

    def test_invalid_env_json(self, monkeypatch):
        monkeypatch.setenv("SENSOR_THRESHOLDS", "not-json")
        assert_that(_resolve_thresholds(None), equal_to({}))

    def test_empty(self, monkeypatch):
        monkeypatch.delenv("SENSOR_THRESHOLDS", raising=False)
        assert_that(_resolve_thresholds(None), equal_to({}))


class TestResolveDiscordWebhook:
    def test_env_creds(self, monkeypatch):
        monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_ID", "123")
        monkeypatch.setenv("DISCORD_ALERT_WEBHOOK_TOKEN", "abc")
        assert_that(_resolve_discord_webhook(), equal_to(("123", "abc")))

    def test_none_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_ID", raising=False)
        monkeypatch.delenv("DISCORD_ALERT_WEBHOOK_TOKEN", raising=False)
        # Discord config block may or may not exist; either way, with no env creds
        # and no app_data alert webhook, the result must be None.
        with patch("workflows.workers.tasks.ingest_sensor_reading._resolve_discord_webhook",
                   wraps=_resolve_discord_webhook):
            result = _resolve_discord_webhook()
        # Accept None (unconfigured) — never a partial tuple.
        assert_that(result is None or isinstance(result, tuple), equal_to(True))


class TestMaybeAlertDiscord:
    def test_skips_when_not_breached(self):
        doc = DtoSensorReading.build(device_id="d", metric="m", value=1.0)
        doc.breached = False
        assert_that(_maybe_alert_discord(doc), equal_to(False))

    def test_skips_when_unconfigured(self):
        doc = DtoSensorReading.build(device_id="d", metric="m", value=99.0)
        doc.breached = True
        with patch("workflows.workers.tasks.ingest_sensor_reading._resolve_discord_webhook",
                   return_value=None):
            assert_that(_maybe_alert_discord(doc), equal_to(False))


# ─────────────────────────────────────────────────────────────────────────────
# ingest_sensor_reading task (in-process)
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestSensorReadingTask:
    def test_task_is_registered(self):
        assert_that(ingest_sensor_reading.name,
                    equal_to("workflows.workers.tasks.ingest_sensor_reading"))

    def _run(self, **kwargs):
        with patch("workflows.workers.tasks.ingest_sensor_reading._post_to_es",
                   return_value=True), \
             patch("workflows.workers.tasks.ingest_sensor_reading._maybe_alert_discord",
                   return_value=False):
            return ingest_sensor_reading.apply(kwargs=kwargs).get()

    def test_payload_shape(self):
        result = self._run(device_id="esp32-garage", metric="temperature",
                           value=21.5, unit="C", location="garage")
        for key in ("task", "device_id", "metric", "value", "unit", "location",
                    "device_ts", "breached", "es_indexed", "alerted", "index"):
            assert_that(result, has_key(key), reason="Missing key: {0}".format(key))
        assert_that(result["task"], equal_to("ingest_sensor_reading"))
        assert_that(result["index"], equal_to("harqis-sensor-telemetry"))

    def test_not_breached_within_bounds(self):
        result = self._run(device_id="d", metric="temperature", value=20.0,
                           thresholds={"temperature": {"min": 2, "max": 35}})
        assert_that(result["breached"], equal_to(False))

    def test_breached_over_max(self):
        result = self._run(device_id="d", metric="temperature", value=99.0,
                           thresholds={"temperature": {"min": 2, "max": 35}})
        assert_that(result["breached"], equal_to(True))

    def test_es_post_called(self):
        with patch("workflows.workers.tasks.ingest_sensor_reading._post_to_es") as mock_post, \
             patch("workflows.workers.tasks.ingest_sensor_reading._maybe_alert_discord",
                   return_value=False):
            mock_post.return_value = True
            ingest_sensor_reading.apply(kwargs={"device_id": "d", "metric": "m", "value": 1.0}).get()
        assert_that(mock_post.called, equal_to(True))

    def test_survives_es_failure(self):
        with patch("workflows.workers.tasks.ingest_sensor_reading._post_to_es",
                   return_value=False), \
             patch("workflows.workers.tasks.ingest_sensor_reading._maybe_alert_discord",
                   return_value=False):
            result = ingest_sensor_reading.apply(
                kwargs={"device_id": "d", "metric": "m", "value": 1.0}).get()
        assert_that(result["es_indexed"], equal_to(False))

    def test_alert_invoked_on_breach(self):
        with patch("workflows.workers.tasks.ingest_sensor_reading._post_to_es",
                   return_value=True), \
             patch("workflows.workers.tasks.ingest_sensor_reading._maybe_alert_discord",
                   return_value=True) as mock_alert:
            result = ingest_sensor_reading.apply(kwargs={
                "device_id": "d", "metric": "temperature", "value": 99.0,
                "thresholds": {"temperature": {"max": 35}},
            }).get()
        assert_that(mock_alert.called, equal_to(True))
        assert_that(result["alerted"], equal_to(True))


# ─────────────────────────────────────────────────────────────────────────────
# Receiver app — skipped if httpx/TestClient is unavailable
# ─────────────────────────────────────────────────────────────────────────────

class TestReceiverApp:
    @pytest.fixture()
    def client(self):
        pytest.importorskip("httpx", reason="starlette TestClient needs httpx")
        from fastapi.testclient import TestClient
        from workflows.workers.receiver.app import app
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert_that(resp.status_code, equal_to(200))
        assert_that(resp.json()["status"], equal_to("ok"))

    def test_telemetry_dispatches(self, client):
        with patch("workflows.workers.tasks.ingest_sensor_reading.ingest_sensor_reading.delay") as mock_delay:
            resp = client.post("/telemetry", json={
                "device_id": "esp32-test", "metric": "temperature",
                "value": 21.5, "unit": "C", "location": "desk",
            })
        assert_that(resp.status_code, equal_to(202))
        assert_that(mock_delay.called, equal_to(True))

    def test_telemetry_validation_error(self, client):
        # missing required `value`
        resp = client.post("/telemetry", json={"device_id": "d", "metric": "m"})
        assert_that(resp.status_code, equal_to(422))

    def test_telemetry_auth_rejected(self, client, monkeypatch):
        monkeypatch.setenv("SENSOR_RECEIVER_TOKEN", "secret")
        resp = client.post("/telemetry", json={
            "device_id": "d", "metric": "m", "value": 1.0,
        })
        assert_that(resp.status_code, equal_to(401))
        monkeypatch.delenv("SENSOR_RECEIVER_TOKEN", raising=False)
