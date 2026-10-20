import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from workflows.hfl.source_health import (
    EntryEvidence,
    HealthSnapshot,
    SourceHealth,
    TaskEvidence,
    UpstreamEvidence,
    evaluate_source,
    load_live_corpus_evidence,
    load_live_es_evidence,
    load_source_registry,
    probe_agent_sessions,
    render_failure_report,
    validate_registry_coverage,
    write_failure_report,
)
from workflows.hfl.tasks.check_activity_corpus_sources import (
    run_activity_corpus_source_check,
)


TZ = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 8, 22, 7, 0, tzinfo=TZ)


# ── Workflow (integration) ────────────────────────────────────────────────────


@pytest.mark.skip(reason="Manual only — queries live HFL corpus/ES and may write a failure report, HFL audit, and Telegram notification")
def test__check_activity_corpus_sources_live_pipeline():
    run_activity_corpus_source_check(mode="weekly")


# ── Unit / function ───────────────────────────────────────────────────────────


def _policy(key: str = "example", **overrides):
    _, policies = load_source_registry()
    base = next(item for item in policies if item.key == "agent-session")
    values = {
        "key": key,
        "kind": base.kind,
        "monitor_mode": base.monitor_mode,
        "task": base.task,
        "entry_sources": base.entry_sources,
        "schedule": base.schedule,
        "expects_entry": base.expects_entry,
        "allow_empty": base.allow_empty,
        "auto_retry": base.auto_retry,
        "backfill": base.backfill,
        "task_max_age_hours": base.task_max_age_hours,
        "entry_max_age_hours": base.entry_max_age_hours,
        "upstream_probe": base.upstream_probe,
        "depends_on": base.depends_on,
        "related_tasks": base.related_tasks,
    }
    values.update(overrides)
    return type(base)(**values)


def test__registry_covers_every_active_hfl_task():
    settings, policies = load_source_registry()

    assert settings["max_backfill_days"] == 15
    assert validate_registry_coverage(policies) == []
    assert {item.monitor_mode for item in policies} >= {
        "scheduled", "manual", "event", "hermes", "unscheduled", "self",
    }


@pytest.mark.parametrize('age_hours, failed, expected', [
    (1, False, 'healthy'), (191, False, 'healthy'),
    (193, False, 'failed'), (1, True, 'failed'),
])
def test__persona_audit_monitors_task_without_public_receipt(age_hours, failed, expected):
    _, policies = load_source_registry()
    policy = next(item for item in policies if item.key == 'persona-audit')
    assert policy.task == 'workflows.hfl.tasks.persona_audit.persona_audit'
    assert policy.monitor_mode == 'scheduled'
    assert not policy.expects_entry
    assert not policy.entry_sources
    assert not policy.auto_retry
    when = NOW - timedelta(hours=age_hours)
    result = evaluate_source(
        policy, now=NOW, corpus={}, elasticsearch={},
        tasks={policy.task: TaskEvidence(
            when=when, last_failed=when if failed else None,
            passed=0 if failed else 1, failed=int(failed),
        )},
    )
    assert result.status == expected


def test__weekly_summary_is_intentionally_unscheduled():
    from workflows.hfl.source_health import configured_hfl_tasks

    _, policies = load_source_registry()
    policy = next(item for item in policies if item.key == "weekly-summary")
    assert policy.task not in configured_hfl_tasks()
    assert policy.monitor_mode == "unscheduled"
    assert policy.task_max_age_hours is None
    assert policy.entry_max_age_hours is None
    assert not policy.auto_retry
    assert policy.backfill == "none"
    result = evaluate_source(policy, now=NOW, corpus={}, elasticsearch={}, tasks={})
    assert result.status == "unmonitored"


def test__weekly_retrieval_is_intentionally_unscheduled():
    from workflows.hfl.source_health import configured_hfl_tasks

    _, policies = load_source_registry()
    policy = next(item for item in policies if item.key == "weekly-retrieval")
    assert policy.task not in configured_hfl_tasks()
    assert policy.monitor_mode == "unscheduled"
    assert policy.task_max_age_hours is None
    assert not policy.auto_retry
    result = evaluate_source(policy, now=NOW, corpus={}, elasticsearch={}, tasks={})
    assert result.status == "unmonitored"


@pytest.mark.parametrize("paused, mismatch, expected", [
    (True, False, "unmonitored"), (True, True, "failed"),
    (False, False, "failed"),
])
def test__hermes_pause_only_suspends_freshness(paused, mismatch, expected):
    _, policies = load_source_registry()
    policy = next(item for item in policies if item.key == "activity-radar")
    old = NOW - timedelta(days=20)
    result = evaluate_source(
        policy, now=NOW,
        corpus={"activity-radar": EntryEvidence(old, "hfl-one")},
        elasticsearch={"activity-radar": EntryEvidence(old, "hfl-two" if mismatch else "hfl-one")},
        tasks={policy.task: TaskEvidence(old, passed=10)},
        scheduler={"available": True, "job_id": "92a8b3452c78",
                   "enabled": not paused, "state": "paused" if paused else "scheduled",
                   "paused_at": old.isoformat(), "last_status": "ok",
                   "last_run_at": old.isoformat(), "schedule": "0 8,12,16,20 * * *"},
    )
    assert result.status == expected
    assert result.evidence["scheduler"]["enabled"] is not paused
    assert ("scheduled task heartbeat is stale or missing" in result.reasons) is not paused


@pytest.mark.parametrize("payload", [None, "invalid json", '{"jobs": []}', '{"jobs": [null]}'])
def test__hermes_scheduler_unavailable_is_not_a_pause(tmp_path, payload):
    from workflows.hfl.source_health import load_hermes_scheduler_evidence

    path = tmp_path / "jobs.json"
    if payload is not None:
        path.write_text(payload)
    evidence = load_hermes_scheduler_evidence(["job-one"], path=path)
    assert evidence["job-one"]["available"] is False


def test__scan_reads_exact_hermes_job_without_changing_it(tmp_path, monkeypatch):
    import json
    from workflows.hfl.source_health import scan_activity_corpus_sources

    home = tmp_path / "hermes"
    (home / "cron").mkdir(parents=True)
    path = home / "cron" / "jobs.json"
    raw = json.dumps({"jobs": [
        {"id": "unrelated", "enabled": True, "state": "scheduled"},
        {"id": "92a8b3452c78", "enabled": False, "state": "paused",
         "paused_at": NOW.isoformat(), "last_status": "ok",
         "last_run_at": (NOW - timedelta(days=20)).isoformat(),
         "schedule": {"expr": "0 8,12,16,20 * * *"}},
    ]})
    path.write_text(raw)
    monkeypatch.setenv("HERMES_HOME", str(home))
    snapshot = scan_activity_corpus_sources(
        now=NOW, corpus_loader=lambda _: {}, es_loader=lambda _: {},
        task_loader=lambda _: {}, upstream_loader=lambda **_: UpstreamEvidence(),
    )
    result = next(item for item in snapshot.sources if item.key == "activity-radar")
    assert result.status == "unmonitored"
    assert result.evidence["scheduler"]["schedule"] == "0 8,12,16,20 * * *"
    assert path.read_text() == raw


@pytest.mark.parametrize("scheduler, expected", [
    (None, "degraded"),
    ({"available": False}, "degraded"),
    ({"available": True, "job_id": "different", "enabled": False, "state": "paused"}, "degraded"),
    ({"available": True, "job_id": "92a8b3452c78", "enabled": True, "state": "paused", "last_status": "error"}, "failed"),
    ({"available": True, "job_id": "92a8b3452c78", "enabled": True, "state": "scheduled", "last_status": "ok"}, "healthy"),
])
def test__hermes_missing_or_failed_scheduler_is_not_suppressed(scheduler, expected):
    _, policies = load_source_registry()
    policy = next(item for item in policies if item.key == "activity-radar")
    fresh = NOW - timedelta(minutes=10)
    result = evaluate_source(
        policy, now=NOW, scheduler=scheduler,
        corpus={"activity-radar": EntryEvidence(fresh, "hfl-one")},
        elasticsearch={"activity-radar": EntryEvidence(fresh, "hfl-one")},
        tasks={policy.task: TaskEvidence(fresh, passed=1)},
    )
    assert result.status == expected


def test__evaluate_source_identifies_hermes_capture_gap_not_es_failure():
    policy = _policy()
    old = NOW - timedelta(days=12)
    result = evaluate_source(
        policy,
        now=NOW,
        corpus={"agent-session": EntryEvidence(old, "hfl-old")},
        elasticsearch={"agent-session": EntryEvidence(old, "hfl-old")},
        tasks={policy.task: TaskEvidence(NOW - timedelta(minutes=10), passed=50)},
        upstream=UpstreamEvidence(
            latest_activity=NOW - timedelta(hours=1),
            latest_capture=old,
            pending=0,
            available=True,
            details=("Hermes state activity found",),
        ),
    )

    assert result.status == "failed"
    assert "upstream activity is newer than captured audit evidence" in result.reasons
    assert "scheduled ingest is still running but has no captured input" in result.suspected_cause
    assert not any("Elasticsearch" in reason for reason in result.reasons)
    assert any("Backfill" in recommendation for recommendation in result.recommendations)


def test__evaluate_source_accepts_proven_empty_success():
    policy = _policy(entry_max_age_hours=24, upstream_probe="")
    result = evaluate_source(
        policy,
        now=NOW,
        corpus={"agent-session": EntryEvidence(NOW - timedelta(days=4), "hfl-old")},
        elasticsearch={"agent-session": EntryEvidence(NOW - timedelta(days=4), "hfl-old")},
        tasks={policy.task: TaskEvidence(NOW - timedelta(minutes=10), passed=20)},
    )

    assert result.status == "healthy-empty"
    assert result.reasons == [
        "task ran successfully and no upstream activity requires an entry"
    ]


def test__evaluate_source_accepts_equal_timestamp_id_sets_in_different_orders():
    policy = _policy(entry_max_age_hours=24)
    latest = NOW - timedelta(hours=1)

    result = evaluate_source(
        policy,
        now=NOW,
        corpus={
            "agent-session": EntryEvidence(
                latest, "hfl-b", entry_ids=("hfl-b", "hfl-a", "hfl-c")
            )
        },
        elasticsearch={
            "agent-session": EntryEvidence(
                latest, "hfl-a", entry_ids=("hfl-a", "hfl-c", "hfl-b")
            )
        },
        tasks={policy.task: TaskEvidence(NOW - timedelta(minutes=5), passed=2)},
    )

    assert result.status == "healthy"
    assert "latest Markdown and Elasticsearch entries do not match" not in result.reasons


def test__load_live_corpus_evidence_retains_all_ids_at_latest_timestamp(monkeypatch, tmp_path):
    when = "2026-08-28T22:29:49+08:00"
    scanned = SimpleNamespace(documents={
        "one": {"source": "notes", "when": when, "entry_id": "hfl-b"},
        "two": {"source": "notes", "when": when, "entry_id": "hfl-a"},
        "old": {
            "source": "notes",
            "when": "2026-08-27T22:29:49+08:00",
            "entry_id": "hfl-old",
        },
    })
    reconcile = __import__(
        "scripts.agents.hfl.reconcile_elasticsearch", fromlist=["scan_corpus"]
    )
    capture = __import__("workflows.hfl.tasks.capture", fromlist=["resolve_corpus_dir"])
    monkeypatch.setattr(reconcile, "scan_corpus", lambda root: scanned)
    monkeypatch.setattr(capture, "resolve_corpus_dir", lambda: tmp_path)

    evidence = load_live_corpus_evidence(["notes"])["notes"]

    assert evidence.entry_ids == ("hfl-a", "hfl-b")
    assert evidence.entry_id in evidence.entry_ids


def test__load_live_corpus_evidence_recognizes_weekly_rollup_artifact(monkeypatch, tmp_path):
    rollup = tmp_path / "2026-W34-rollup.md"
    rollup.write_text("# Weekly rollup — 2026-W34\n", encoding="utf-8")
    expected = datetime(2026, 8, 23, 21, 0, 19, tzinfo=TZ)
    os.utime(rollup, (expected.timestamp(), expected.timestamp()))
    reconcile = __import__(
        "scripts.agents.hfl.reconcile_elasticsearch", fromlist=["scan_corpus"]
    )
    capture = __import__("workflows.hfl.tasks.capture", fromlist=["resolve_corpus_dir"])
    monkeypatch.setattr(
        reconcile, "scan_corpus", lambda root: SimpleNamespace(documents={})
    )
    monkeypatch.setattr(capture, "resolve_corpus_dir", lambda: tmp_path)

    evidence = load_live_corpus_evidence(["summarize"])["summarize"]

    assert evidence.when == expected
    assert evidence.entry_id == ""


def test__load_live_es_evidence_filters_exact_source_and_retains_latest_ids(monkeypatch):
    es = __import__("workflows.hfl.es_store", fromlist=["HflQueryResult"])
    calls = []

    def fake_query(**kwargs):
        calls.append(kwargs)
        return es.HflQueryResult((
            {
                "source": "activity-radar",
                "when": "2026-08-29T16:02:18+08:00",
                "entry_id": "hfl-wrong",
            },
            {
                "source": "radar",
                "when": "2026-08-28T23:20:13+08:00",
                "entry_id": "hfl-b",
            },
            {
                "source": "radar",
                "when": "2026-08-28T23:20:13+08:00",
                "entry_id": "hfl-a",
            },
        ), available=True)

    monkeypatch.setattr(es, "query_hfl_entries_status", fake_query)

    evidence = load_live_es_evidence(["radar"])["radar"]

    assert calls == [{"source": "radar", "limit": 500}]
    assert evidence.entry_ids == ("hfl-a", "hfl-b")
    assert evidence.entry_id in evidence.entry_ids


def test__probe_agent_sessions_uses_only_eligible_closed_pairs(monkeypatch, tmp_path):
    capture_module = __import__(
        "scripts.agents.hfl.capture_session_event", fromlist=["audit_root"]
    )
    monkeypatch.setattr(capture_module, "audit_root", lambda: tmp_path)
    events = tmp_path / "events" / "2026-08-28"
    events.mkdir(parents=True)
    captured_at = NOW - timedelta(days=1)
    (events / "captured.json").write_text(
        '{"timestamp": "' + captured_at.isoformat()
        + '", "ingest": {"entry_id": "hfl-old"}}',
        encoding="utf-8",
    )
    eligible_at = NOW - timedelta(hours=2)
    calls = []

    def pair_loader(database, *, since, until):
        calls.append((database, since, until))
        return [{"timestamp": eligible_at.isoformat()}]

    evidence = probe_agent_sessions(now=NOW, pair_loader=pair_loader)

    assert evidence.latest_activity == eligible_at
    assert calls[0][1] == captured_at + timedelta(microseconds=1)
    assert calls[0][2] == NOW
    assert "eligible closed CLI/Telegram pairs after capture: 1" in evidence.details


def test__probe_agent_sessions_handles_missing_state_database(monkeypatch, tmp_path):
    capture_module = __import__(
        "scripts.agents.hfl.capture_session_event", fromlist=["audit_root"]
    )
    monkeypatch.setattr(capture_module, "audit_root", lambda: tmp_path / "missing-audit")
    monkeypatch.setenv("HERMES_STATE_DB", str(tmp_path / "missing-state.db"))

    evidence = probe_agent_sessions(now=NOW)

    assert evidence.available is False
    assert evidence.latest_activity is None
    assert evidence.pending == 0


def test__evaluate_source_reports_markdown_es_parity_gap():
    policy = _policy(entry_max_age_hours=24)
    result = evaluate_source(
        policy,
        now=NOW,
        corpus={"agent-session": EntryEvidence(NOW - timedelta(hours=1), "hfl-new")},
        elasticsearch={"agent-session": EntryEvidence()},
        tasks={policy.task: TaskEvidence(NOW - timedelta(minutes=5), passed=2)},
    )

    assert result.status == "failed"
    assert "Markdown entry has no Elasticsearch projection" in result.reasons
    assert any("reconcile_elasticsearch.py" in item for item in result.recommendations)


def test__evaluate_source_reports_latest_task_failure():
    policy = _policy(entry_max_age_hours=24)
    failed_at = NOW - timedelta(minutes=5)
    result = evaluate_source(
        policy,
        now=NOW,
        corpus={"agent-session": EntryEvidence(NOW - timedelta(hours=1), "hfl-new")},
        elasticsearch={"agent-session": EntryEvidence(NOW - timedelta(hours=1), "hfl-new")},
        tasks={
            policy.task: TaskEvidence(
                when=failed_at, last_failed=failed_at, passed=10, failed=1,
            )
        },
    )

    assert result.status == "failed"
    assert "latest observed task execution failed" in result.reasons
    assert result.evidence["task"]["last_success"] is None


def test__write_failure_report_is_failure_only(tmp_path):
    healthy = HealthSnapshot(
        generated_at=NOW.isoformat(),
        mode="daily",
        timezone="Asia/Singapore",
        max_backfill_days=15,
        sources=[SourceHealth("git", "source", "healthy", "daily", "task", ["git"])],
    )

    assert write_failure_report(healthy, results_dir=tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test__write_failure_report_is_atomic_and_mode_scoped(tmp_path):
    failed = SourceHealth(
        "git", "source", "failed", "daily", "task", ["git"],
        reasons=["scheduled task heartbeat is stale or missing"],
    )
    snapshot = HealthSnapshot(
        generated_at=NOW.isoformat(), mode="weekly", timezone="Asia/Singapore",
        max_backfill_days=15, sources=[failed], correlation_id="correlation-1",
    )

    path = write_failure_report(snapshot, results_dir=tmp_path)

    assert path is not None
    assert path.name == "activity-corpus-source-failures-weekly-20260822-070000.md"
    assert "Correlation ID: correlation-1" in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


def test__render_failure_report_contains_required_source_evidence():
    failed = SourceHealth(
        key="agent-session",
        kind="source",
        status="failed",
        schedule="every 10 minutes",
        task="workflows.hfl.tasks.ingest_agent_sessions.ingest_agent_session_events",
        entry_sources=["agent-session"],
        reasons=["upstream activity is newer than captured audit evidence"],
        evidence={
            "task": {
                "last_run": "2026-08-22T06:50:00+08:00",
                "last_success": "2026-08-22T06:50:00+08:00",
            },
            "corpus": {"last_entry": "2026-08-10T12:43:48+08:00"},
            "elasticsearch": {"last_entry": "2026-08-10T12:43:48+08:00"},
            "upstream": {
                "latest_activity": "2026-08-22T06:00:00+08:00",
                "latest_capture": "2026-08-10T13:25:00+08:00",
                "pending": 0,
            },
        },
        suspected_cause="collector wiring stopped",
        recommendations=["Backfill retained sessions."],
    )
    snapshot = HealthSnapshot(
        generated_at=NOW.isoformat(), mode="daily", timezone="Asia/Singapore",
        max_backfill_days=15, sources=[failed],
    )

    report = render_failure_report(snapshot)

    assert "Last task heartbeat" in report
    assert "Last successful execution" in report
    assert "Last corpus entry" in report
    assert "Last Elasticsearch document" in report
    assert "Actions performed" in report
    assert "Task/commit identifiers" in report
    assert "Remaining risk" in report


def test__run_activity_corpus_source_check_has_no_healthy_side_effects(monkeypatch):
    healthy = HealthSnapshot(
        generated_at=NOW.isoformat(), mode="weekly", timezone="Asia/Singapore",
        max_backfill_days=15,
        sources=[SourceHealth("git", "source", "healthy", "daily", "task", ["git"])],
    )
    module = __import__(
        "workflows.hfl.tasks.check_activity_corpus_sources", fromlist=["module"]
    )
    monkeypatch.setattr(module, "scan_activity_corpus_sources", lambda **kwargs: healthy)
    monkeypatch.setattr(module, "write_failure_report", lambda *args, **kwargs: pytest.fail("report written"))
    monkeypatch.setattr(module, "_write_hfl_audit", lambda *args, **kwargs: pytest.fail("HFL written"))
    monkeypatch.setattr(module, "_notify_telegram", lambda *args, **kwargs: pytest.fail("Telegram sent"))

    result = run_activity_corpus_source_check(mode="weekly")

    assert result["status"] == "healthy"
    assert result["failure_count"] == 0
