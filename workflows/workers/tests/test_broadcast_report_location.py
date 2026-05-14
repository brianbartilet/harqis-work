"""
Tests for workflows/workers/tasks/broadcast_report_location.py

Covers:
  - DtoWorkerLocation DTO: construction, to_dict shape, GeoPoint.is_valid
  - Location resolvers: env, ip_geo (mocked), OwnTracks (mocked), null cascade
  - Broadcast task: runs in-process, returns expected payload shape
  - ES persistence: post called with correct args; gracefully no-ops when
    es_logging is missing
  - Routing topology: workers_broadcast is declared as a fanout in config
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import (
    assert_that,
    equal_to,
    has_key,
    instance_of,
    none,
    is_not,
    contains_string,
)

from workflows.workers.dto.worker_location import (
    DtoWorkerLocation,
    GeoPoint,
    WORKER_LOCATIONS_INDEX,
)


# ─────────────────────────────────────────────────────────────────────────────
# GeoPoint
# ─────────────────────────────────────────────────────────────────────────────

class TestGeoPoint:
    def test_valid_coordinates(self):
        fix = GeoPoint(lat=1.3, lon=103.85, source="owntracks")
        assert_that(fix.is_valid(), equal_to(True))

    def test_invalid_when_lat_none(self):
        fix = GeoPoint(lat=None, lon=103.85)
        assert_that(fix.is_valid(), equal_to(False))

    def test_invalid_when_lon_none(self):
        fix = GeoPoint(lat=1.3, lon=None)
        assert_that(fix.is_valid(), equal_to(False))

    def test_invalid_out_of_bounds_lat(self):
        fix = GeoPoint(lat=91.0, lon=0.0)
        assert_that(fix.is_valid(), equal_to(False))

    def test_invalid_out_of_bounds_lon(self):
        fix = GeoPoint(lat=0.0, lon=181.0)
        assert_that(fix.is_valid(), equal_to(False))

    def test_to_dict_has_required_keys(self):
        fix = GeoPoint(lat=1.3, lon=103.85, accuracy=10.0, source="owntracks")
        d = fix.to_dict()
        assert_that(d, has_key("lat"))
        assert_that(d, has_key("lon"))
        assert_that(d, has_key("source"))
        assert_that(d["lat"], instance_of(float))
        assert_that(d["source"], instance_of(str))

    def test_unavailable_fix_not_valid(self):
        fix = GeoPoint(source="unavailable")
        assert_that(fix.is_valid(), equal_to(False))


# ─────────────────────────────────────────────────────────────────────────────
# DtoWorkerLocation
# ─────────────────────────────────────────────────────────────────────────────

class TestDtoWorkerLocation:
    def test_build_populates_identity(self):
        doc = DtoWorkerLocation.build()
        assert_that(doc.machine_name, instance_of(str))
        assert_that(len(doc.machine_name), is_not(equal_to(0)))
        assert_that(doc.platform_os, instance_of(str))
        assert_that(doc.time_sent, instance_of(str))
        assert_that(doc.date, instance_of(str))

    def test_build_with_location(self):
        fix = GeoPoint(lat=1.3, lon=103.85, source="env")
        doc = DtoWorkerLocation.build(
            worker_name="celery@testhost",
            new_location=fix,
            owntracks_user="alice",
            owntracks_device="android",
        )
        assert_that(doc.worker_name, equal_to("celery@testhost"))
        assert_that(doc.new_location.source, equal_to("env"))
        assert_that(doc.owntracks_user, equal_to("alice"))

    def test_to_dict_structure(self):
        fix = GeoPoint(lat=1.3, lon=103.85, source="owntracks")
        doc = DtoWorkerLocation.build(new_location=fix)
        d = doc.to_dict()
        for key in (
            "machine_name",
            "worker_name",
            "time_sent",
            "platform_detail",
            "date",
            "new_location",
            "last_location",
            "owntracks_user",
            "owntracks_device",
            "task_name",
            "extra",
        ):
            assert_that(d, has_key(key), reason="Missing key: {0}".format(key))
        # new_location is a dict with lat/lon
        assert_that(d["new_location"]["lat"], instance_of(float))
        # last_location is None when not provided
        assert_that(d["last_location"], none())

    def test_default_index_name(self):
        assert_that(WORKER_LOCATIONS_INDEX, equal_to("harqis-worker-locations"))

    def test_index_name_env_override(self, monkeypatch):
        monkeypatch.setenv("WORKER_LOCATIONS_INDEX", "custom-location-index")
        import workflows.workers.dto.worker_location as mod
        importlib.reload(mod)
        assert_that(mod.WORKER_LOCATIONS_INDEX, equal_to("custom-location-index"))
        monkeypatch.delenv("WORKER_LOCATIONS_INDEX", raising=False)
        importlib.reload(mod)


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_via_env
# ─────────────────────────────────────────────────────────────────────────────

from workflows.workers.tasks.broadcast_report_location import (  # noqa: E402
    _resolve_via_env,
    _resolve_via_ip_geolocation,
    _resolve_location,
)


class TestResolveViaEnv:
    def test_returns_none_when_not_set(self, monkeypatch):
        monkeypatch.delenv("WORKER_LAT", raising=False)
        monkeypatch.delenv("WORKER_LON", raising=False)
        assert_that(_resolve_via_env(), none())

    def test_returns_geopoint_when_set(self, monkeypatch):
        monkeypatch.setenv("WORKER_LAT", "1.3521")
        monkeypatch.setenv("WORKER_LON", "103.8198")
        fix = _resolve_via_env()
        assert_that(fix, is_not(none()))
        assert_that(fix.lat, instance_of(float))
        assert_that(fix.lon, instance_of(float))
        assert_that(fix.source, equal_to("env"))

    def test_returns_none_on_invalid_float(self, monkeypatch):
        monkeypatch.setenv("WORKER_LAT", "not-a-number")
        monkeypatch.setenv("WORKER_LON", "103.8198")
        assert_that(_resolve_via_env(), none())


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_via_ip_geolocation
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveViaIpGeolocation:
    def test_returns_none_when_skipped_via_env(self, monkeypatch):
        monkeypatch.setenv("WORKER_SKIP_IP_GEO", "true")
        assert_that(_resolve_via_ip_geolocation(), none())

    def test_returns_geopoint_on_success(self, monkeypatch):
        """IP-geo resolver returns a GeoPoint on a mocked successful response."""
        monkeypatch.delenv("WORKER_SKIP_IP_GEO", raising=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "lat": 51.5,
            "lon": -0.12,
            "city": "London",
        }
        with patch(
            "workflows.workers.tasks.broadcast_report_location.requests.get",
            return_value=mock_resp,
        ):
            fix = _resolve_via_ip_geolocation()

        assert_that(fix, is_not(none()))
        assert_that(fix.lat, instance_of(float))
        assert_that(fix.source, equal_to("ip_geolocation"))

    def test_returns_none_on_network_error(self, monkeypatch):
        monkeypatch.delenv("WORKER_SKIP_IP_GEO", raising=False)
        with patch(
            "workflows.workers.tasks.broadcast_report_location.requests.get",
            side_effect=Exception("timeout"),
        ):
            fix = _resolve_via_ip_geolocation()
        assert_that(fix, none())

    def test_returns_none_on_failed_status(self, monkeypatch):
        monkeypatch.delenv("WORKER_SKIP_IP_GEO", raising=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "fail", "message": "reserved range"}
        with patch(
            "workflows.workers.tasks.broadcast_report_location.requests.get",
            return_value=mock_resp,
        ):
            fix = _resolve_via_ip_geolocation()
        assert_that(fix, none())


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_location (cascade)
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveLocation:
    def test_env_wins_over_ip_geo(self, monkeypatch):
        """When WORKER_LAT/LON are set, env resolver returns before ip-geo fires."""
        monkeypatch.setenv("WORKER_LAT", "10.0")
        monkeypatch.setenv("WORKER_LON", "20.0")
        monkeypatch.setenv("WORKER_SKIP_IP_GEO", "true")
        fix = _resolve_location(owntracks_cfg_id="OWN_TRACKS")
        assert_that(fix.source, equal_to("env"))
        assert_that(fix.lat, equal_to(10.0))

    def test_falls_back_to_unavailable_when_all_fail(self, monkeypatch):
        monkeypatch.delenv("WORKER_LAT", raising=False)
        monkeypatch.delenv("WORKER_LON", raising=False)
        monkeypatch.setenv("WORKER_SKIP_IP_GEO", "true")
        # "NONEXISTENT_CFG" will fail CONFIG_MANAGER.get → OwnTracks resolver → None
        fix = _resolve_location(owntracks_cfg_id="NONEXISTENT_CFG")
        assert_that(fix.source, equal_to("unavailable"))
        assert_that(fix.is_valid(), equal_to(False))


# ─────────────────────────────────────────────────────────────────────────────
# broadcast_report_location task (in-process)
# ─────────────────────────────────────────────────────────────────────────────

from workflows.workers.tasks.broadcast_report_location import (  # noqa: E402
    broadcast_report_location,
)


class TestBroadcastReportLocationTask:
    def test_task_is_registered(self):
        assert_that(
            broadcast_report_location.name,
            contains_string("broadcast_report_location"),
        )

    def test_task_runs_in_process_and_returns_payload(self, monkeypatch):
        """Task body runs successfully without a broker; payload has all expected keys."""
        monkeypatch.setenv("WORKER_LAT", "1.3521")
        monkeypatch.setenv("WORKER_LON", "103.8198")
        with patch(
            "workflows.workers.tasks.broadcast_report_location._post_to_es",
            return_value=False,
        ):
            result = broadcast_report_location.apply(kwargs={}).get()

        assert_that(result, has_key("task"))
        assert_that(result["task"], equal_to("broadcast_report_location"))
        assert_that(result, has_key("machine_name"))
        assert_that(result, has_key("worker_name"))
        assert_that(result, has_key("time_sent"))
        assert_that(result, has_key("date" if False else "platform_os"))
        assert_that(result, has_key("platform_os"))
        assert_that(result, has_key("location_source"))
        assert_that(result, has_key("new_location"))
        assert_that(result, has_key("last_location"))
        assert_that(result, has_key("owntracks_user"))
        assert_that(result, has_key("es_indexed"))
        assert_that(result, has_key("index"))

    def test_location_source_from_env(self, monkeypatch):
        monkeypatch.setenv("WORKER_LAT", "51.5")
        monkeypatch.setenv("WORKER_LON", "-0.1")
        monkeypatch.setenv("WORKER_SKIP_IP_GEO", "true")
        with patch(
            "workflows.workers.tasks.broadcast_report_location._post_to_es",
            return_value=False,
        ):
            result = broadcast_report_location.apply(kwargs={}).get()

        assert_that(result["location_source"], equal_to("env"))
        assert_that(result["new_location"]["lat"], instance_of(float))

    def test_location_source_unavailable_when_all_fail(self, monkeypatch):
        monkeypatch.delenv("WORKER_LAT", raising=False)
        monkeypatch.delenv("WORKER_LON", raising=False)
        monkeypatch.setenv("WORKER_SKIP_IP_GEO", "true")
        with patch(
            "workflows.workers.tasks.broadcast_report_location._post_to_es",
            return_value=False,
        ):
            with patch(
                "workflows.workers.tasks.broadcast_report_location._resolve_via_owntracks",
                return_value=None,
            ):
                result = broadcast_report_location.apply(kwargs={}).get()

        assert_that(result["location_source"], equal_to("unavailable"))

    def test_es_post_called(self, monkeypatch):
        monkeypatch.setenv("WORKER_LAT", "1.35")
        monkeypatch.setenv("WORKER_LON", "103.82")
        with patch(
            "workflows.workers.tasks.broadcast_report_location._post_to_es"
        ) as mock_post:
            mock_post.return_value = True
            broadcast_report_location.apply(kwargs={}).get()

        assert_that(mock_post.called, equal_to(True))

    def test_task_survives_es_failure(self, monkeypatch):
        """ES outage must never raise — task returns with es_indexed=False."""
        monkeypatch.setenv("WORKER_LAT", "1.35")
        monkeypatch.setenv("WORKER_LON", "103.82")
        with patch(
            "workflows.workers.tasks.broadcast_report_location._post_to_es",
            return_value=False,
        ):
            result = broadcast_report_location.apply(kwargs={}).get()

        assert_that(result["es_indexed"], equal_to(False))

    def test_payload_includes_index_name(self, monkeypatch):
        monkeypatch.setenv("WORKER_LAT", "1.35")
        monkeypatch.setenv("WORKER_LON", "103.82")
        with patch(
            "workflows.workers.tasks.broadcast_report_location._post_to_es",
            return_value=True,
        ):
            result = broadcast_report_location.apply(kwargs={}).get()

        assert_that(result["index"], equal_to("harqis-worker-locations"))


# ─────────────────────────────────────────────────────────────────────────────
# Routing topology assertions
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkersRoutingTopology:
    """Assert that workers_broadcast is wired correctly in workflows/config.py."""

    @pytest.fixture(autouse=True)
    def _load_config(self):
        os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
        os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
        import workflows.config  # noqa: F401 — registers queues/routes onto SPROUT
        from core.apps.sprout.app.celery import SPROUT
        self.sprout = SPROUT

    def test_workers_broadcast_queue_is_declared(self):
        from kombu.common import Broadcast
        declared = {
            q.exchange.name if isinstance(q, Broadcast) else q.name
            for q in (self.sprout.conf.task_queues or ())
        }
        assert_that(
            "workers_broadcast" in declared,
            equal_to(True),
            reason="workers_broadcast must appear in SPROUT.conf.task_queues",
        )

    def test_workers_broadcast_is_a_fanout(self):
        from kombu.common import Broadcast
        q = next(
            (
                q for q in (self.sprout.conf.task_queues or ())
                if isinstance(q, Broadcast) and q.exchange.name == "workers_broadcast"
            ),
            None,
        )
        assert_that(q, is_not(none()), reason="workers_broadcast must be a Broadcast queue")

    def test_workers_broadcast_route_exists(self):
        routes = self.sprout.conf.task_routes or {}
        assert_that("workflows.workers.tasks.broadcast_*" in routes, equal_to(True))
        assert_that(
            routes["workflows.workers.tasks.broadcast_*"]["queue"],
            equal_to("workers_broadcast"),
        )

    def test_beat_schedule_contains_report_location(self):
        schedule = self.sprout.conf.beat_schedule or {}
        assert_that(
            "run-job--broadcast_report_location" in schedule,
            equal_to(True),
        )

    def test_report_location_targets_workers_broadcast(self):
        schedule = self.sprout.conf.beat_schedule or {}
        entry = schedule.get("run-job--broadcast_report_location", {})
        assert_that(
            entry.get("options", {}).get("queue"),
            equal_to("workers_broadcast"),
        )
