"""
Tests for scripts/bootstrap_elasticsearch.py.

All HTTP calls are intercepted via monkeypatch — no live Elasticsearch required.
Contract under test: correct template payload, correct index filtering (system
indices excluded), dry-run emits no HTTP calls, and ES unavailability is
non-fatal (returns False, never raises).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_bootstrap_module():
    path = Path(__file__).resolve().parents[1] / "bootstrap_elasticsearch.py"
    spec = importlib.util.spec_from_file_location("harqis_bootstrap_for_test", path)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ── is_harqis_index ───────────────────────────────────────────────────────────

def test_is_harqis_index_matches_harqis_prefix():
    bs = load_bootstrap_module()
    assert bs.is_harqis_index("harqis-elastic-logging") is True
    assert bs.is_harqis_index("harqis-hfl-entries") is True


def test_is_harqis_index_matches_tcg_mp_prefix():
    bs = load_bootstrap_module()
    assert bs.is_harqis_index("tcg-mp-listings") is True
    assert bs.is_harqis_index("tcg-mp-prices") is True


def test_is_harqis_index_rejects_system_indices():
    bs = load_bootstrap_module()
    assert bs.is_harqis_index(".kibana_1") is False
    assert bs.is_harqis_index(".security-7") is False
    assert bs.is_harqis_index(".ds-harqis-something") is False


def test_is_harqis_index_rejects_unrelated():
    bs = load_bootstrap_module()
    assert bs.is_harqis_index("logstash-2024") is False
    assert bs.is_harqis_index("other-index") is False


# ── Template payload ──────────────────────────────────────────────────────────

def test_template_covers_both_index_patterns():
    bs = load_bootstrap_module()
    assert "harqis-*" in bs.INDEX_PATTERNS
    assert "tcg-mp-*" in bs.INDEX_PATTERNS


def test_template_settings_zero_replicas_one_shard():
    bs = load_bootstrap_module()
    s = bs.TEMPLATE_SETTINGS["index"]
    assert s["number_of_replicas"] == "0"
    assert s["number_of_shards"] == "1"


# ── bootstrap dry-run ─────────────────────────────────────────────────────────

def test_bootstrap_dry_run_makes_no_http_calls(monkeypatch):
    bs = load_bootstrap_module()
    calls = []

    def fake_call(method, path, body=None):
        # _wait_ready needs to succeed; template + patch calls should be skipped
        if path == "/_cluster/health":
            return 200, {"status": "green", "cluster_name": "test"}
        calls.append((method, path))
        return 200, {}

    monkeypatch.setattr(bs, "_call", fake_call)
    result = bs.bootstrap(dry_run=True, wait_seconds=5)

    assert result is True
    # Only the health check call should happen; PUT calls must not fire
    put_calls = [(m, p) for m, p in calls if m == "PUT"]
    assert put_calls == [], f"unexpected PUT calls in dry-run: {put_calls}"


def test_bootstrap_dry_run_patches_no_indices(monkeypatch, capsys):
    bs = load_bootstrap_module()

    def fake_call(method, path, body=None):
        if path == "/_cluster/health":
            return 200, {"status": "yellow", "cluster_name": "test"}
        if path == "/_cat/indices?h=index&format=json":
            return 200, [
                {"index": "harqis-elastic-logging"},
                {"index": "harqis-hfl-entries"},
                {"index": ".kibana_1"},
            ]
        return 200, {}

    monkeypatch.setattr(bs, "_call", fake_call)
    bs.bootstrap(dry_run=True, wait_seconds=5)

    out = capsys.readouterr().out
    assert "[dry-run]" in out
    # System index must not appear at all in dry-run output
    assert ".kibana_1" not in out


# ── bootstrap with live-style calls ──────────────────────────────────────────

def test_bootstrap_installs_template_with_correct_payload(monkeypatch):
    bs = load_bootstrap_module()
    captured = {}

    def fake_call(method, path, body=None):
        if path == "/_cluster/health":
            return 200, {"status": "green", "cluster_name": "test"}
        if path == "/_cat/indices?h=index&format=json":
            return 200, []
        if method == "PUT" and "_index_template" in path:
            captured["path"] = path
            captured["body"] = body
            return 200, {"acknowledged": True}
        return 200, {}

    monkeypatch.setattr(bs, "_call", fake_call)
    ok = bs.bootstrap(dry_run=False, wait_seconds=5)

    assert ok is True
    assert captured["path"] == f"/_index_template/{bs.TEMPLATE_NAME}"
    assert captured["body"]["index_patterns"] == bs.INDEX_PATTERNS
    assert captured["body"]["template"]["settings"] == bs.TEMPLATE_SETTINGS


def test_bootstrap_patches_existing_harqis_indices(monkeypatch):
    bs = load_bootstrap_module()
    patched = []

    def fake_call(method, path, body=None):
        if path == "/_cluster/health":
            return 200, {"status": "green", "cluster_name": "test"}
        if path == "/_cat/indices?h=index&format=json":
            return 200, [
                {"index": "harqis-elastic-logging"},
                {"index": "tcg-mp-listings"},
                {"index": ".kibana_1"},        # system — must be skipped
                {"index": "logstash-stuff"},    # unrelated — must be skipped
            ]
        if method == "PUT" and "_settings" in path:
            patched.append(path)
            assert body == {"index": {"number_of_replicas": "0"}}
            return 200, {"acknowledged": True}
        return 200, {}

    monkeypatch.setattr(bs, "_call", fake_call)
    bs.bootstrap(dry_run=False, wait_seconds=5)

    assert "/_cat/indices" not in patched
    assert "/harqis-elastic-logging/_settings" in patched
    assert "/tcg-mp-listings/_settings" in patched
    # System and unrelated indices must NOT be patched
    assert "/.kibana_1/_settings" not in patched
    assert "/logstash-stuff/_settings" not in patched


# ── ES unavailable ────────────────────────────────────────────────────────────

def test_bootstrap_returns_false_when_es_unreachable(monkeypatch):
    bs = load_bootstrap_module()

    def fake_call(method, path, body=None):
        raise OSError("connection refused")

    monkeypatch.setattr(bs, "_call", fake_call)
    result = bs.bootstrap(dry_run=False, wait_seconds=0)

    assert result is False


def test_bootstrap_does_not_raise_when_es_unreachable(monkeypatch):
    bs = load_bootstrap_module()

    def fake_call(method, path, body=None):
        raise ConnectionRefusedError("ES down")

    monkeypatch.setattr(bs, "_call", fake_call)
    # Must not raise — non-fatal in deploy pipeline
    try:
        bs.bootstrap(dry_run=False, wait_seconds=0)
    except Exception as exc:
        raise AssertionError(f"bootstrap raised unexpectedly: {exc}") from exc
