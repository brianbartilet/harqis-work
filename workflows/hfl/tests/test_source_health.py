from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from workflows.hfl.source_health import (
    EntryEvidence,
    HealthSnapshot,
    SourceHealth,
    TaskEvidence,
    UpstreamEvidence,
    evaluate_source,
    load_source_registry,
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
