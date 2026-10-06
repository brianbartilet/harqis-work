"""Deterministic health evidence and classification for HFL source pipelines.

This module deliberately stops at evidence collection and bounded classification.
Adaptive diagnosis, code repair, and recovery selection belong to the
``check-activity-corpus-sources`` agent skill.
"""

from __future__ import annotations

import ast
import json
import os
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "check-activity-corpus-sources"
    / "references"
    / "sources.toml"
)
TASK_CONFIG_PATH = REPO_ROOT / "workflows" / "hfl" / "tasks_config.py"


@dataclass(frozen=True)
class SourcePolicy:
    key: str
    kind: str
    monitor_mode: str
    task: str
    entry_sources: tuple[str, ...]
    schedule: str
    expects_entry: bool
    allow_empty: bool
    auto_retry: bool
    backfill: str
    task_max_age_hours: Optional[float] = None
    entry_max_age_hours: Optional[float] = None
    upstream_probe: str = ""
    depends_on: tuple[str, ...] = ()
    related_tasks: tuple[str, ...] = ()
    hermes_job_id: str = ""


@dataclass(frozen=True)
class EntryEvidence:
    when: Optional[datetime] = None
    entry_id: str = ""
    available: bool = True
    error: str = ""
    entry_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskEvidence:
    when: Optional[datetime] = None
    last_failed: Optional[datetime] = None
    passed: float = 0
    failed: float = 0
    available: bool = True
    error: str = ""


@dataclass(frozen=True)
class UpstreamEvidence:
    latest_activity: Optional[datetime] = None
    latest_capture: Optional[datetime] = None
    pending: Optional[int] = None
    available: bool = False
    details: tuple[str, ...] = ()


@dataclass
class SourceHealth:
    key: str
    kind: str
    status: str
    schedule: str
    task: str
    entry_sources: list[str]
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    suspected_cause: str = ""
    recommendations: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class HealthSnapshot:
    generated_at: str
    mode: str
    timezone: str
    max_backfill_days: int
    sources: list[SourceHealth]
    registry_errors: list[str] = field(default_factory=list)
    correlation_id: str = ""

    @property
    def failures(self) -> list[SourceHealth]:
        return [item for item in self.sources if item.status in {"failed", "degraded"}]

    @property
    def status(self) -> str:
        if any(item.status == "failed" for item in self.sources) or self.registry_errors:
            return "failed"
        if any(item.status == "degraded" for item in self.sources):
            return "degraded"
        return "healthy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status
        payload["failure_count"] = len(self.failures) + len(self.registry_errors)
        return payload


def _parse_when(value: Any, *, default_tz: ZoneInfo) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000
        try:
            parsed = datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
            for pattern in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(default_tz)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def load_source_registry(path: Path = DEFAULT_POLICY_PATH) -> tuple[dict[str, Any], list[SourcePolicy]]:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    policies = []
    for item in raw.get("sources", []):
        policies.append(SourcePolicy(
            key=str(item["key"]),
            kind=str(item.get("kind", "source")),
            monitor_mode=str(item.get("monitor_mode", "manual")),
            task=str(item.get("task", "")),
            entry_sources=tuple(str(value) for value in item.get("entry_sources", [])),
            schedule=str(item.get("schedule", "")),
            expects_entry=bool(item.get("expects_entry", False)),
            allow_empty=bool(item.get("allow_empty", False)),
            auto_retry=bool(item.get("auto_retry", False)),
            backfill=str(item.get("backfill", "none")),
            task_max_age_hours=(
                float(item["task_max_age_hours"])
                if "task_max_age_hours" in item else None
            ),
            entry_max_age_hours=(
                float(item["entry_max_age_hours"])
                if "entry_max_age_hours" in item else None
            ),
            upstream_probe=str(item.get("upstream_probe", "")),
            depends_on=tuple(str(value) for value in item.get("depends_on", [])),
            related_tasks=tuple(str(value) for value in item.get("related_tasks", [])),
            hermes_job_id=str(item.get("hermes_job_id", "")),
        ))
    return dict(raw.get("policy", {})), policies


def configured_hfl_tasks(path: Path = TASK_CONFIG_PATH) -> set[str]:
    """Return active task paths without importing workflow configuration."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    tasks: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "WORKFLOW_HFL" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for value in node.value.values:
            if not isinstance(value, ast.Dict):
                continue
            for key_node, value_node in zip(value.keys, value.values):
                if (
                    isinstance(key_node, ast.Constant)
                    and key_node.value == "task"
                    and isinstance(value_node, ast.Constant)
                    and isinstance(value_node.value, str)
                ):
                    tasks.add(value_node.value)
    return tasks


def public_hfl_tasks(tasks_dir: Path = REPO_ROOT / "workflows" / "hfl" / "tasks") -> set[str]:
    """Return every public ``@SPROUT.task`` path without importing task modules."""
    paths: set[str] = set()
    for path in Path(tasks_dir).glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorated = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "task"
                for decorator in node.decorator_list
            )
            if decorated:
                paths.add(f"workflows.hfl.tasks.{path.stem}.{node.name}")
    return paths


def validate_registry_coverage(
    policies: Iterable[SourcePolicy], *, task_config_path: Path = TASK_CONFIG_PATH,
) -> list[str]:
    policies = list(policies)
    registered = {
        task
        for policy in policies
        for task in (policy.task, *policy.related_tasks)
        if task
    }
    configured = configured_hfl_tasks(task_config_path)
    errors = [
        f"active HFL task is absent from source registry: {task}"
        for task in sorted(configured - registered)
    ]
    errors.extend(
        f"public HFL task is absent from source/related-process registry: {task}"
        for task in sorted(public_hfl_tasks() - registered)
    )
    return errors


def _age_hours(now: datetime, then: Optional[datetime]) -> Optional[float]:
    if then is None:
        return None
    return max(0.0, (now - then.astimezone(now.tzinfo)).total_seconds() / 3600)


def _latest(items: Iterable[EntryEvidence]) -> EntryEvidence:
    values = list(items)
    unavailable = [item for item in values if not item.available]
    dated = [item for item in values if item.when]
    if dated:
        return max(dated, key=lambda item: item.when or datetime.min.replace(tzinfo=timezone.utc))
    if unavailable:
        return unavailable[0]
    return EntryEvidence()


def load_hermes_scheduler_evidence(
    job_ids: Iterable[str], *, path: Optional[Path] = None,
) -> dict[str, dict[str, Any]]:
    """Read exact registered jobs, never mutate scheduler state or infer pauses."""
    job_ids = set(job_ids)
    if not job_ids:
        return {}
    path = path or Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "cron" / "jobs.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        jobs = payload.get("jobs") if isinstance(payload, dict) else payload
        if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
            raise ValueError("invalid jobs list")
    except (OSError, UnicodeError, ValueError) as exc:
        return {job_id: {"available": False, "job_id": job_id,
                         "error": f"scheduler read failed: {type(exc).__name__}"}
                for job_id in job_ids}
    evidence = {}
    for job_id in job_ids:
        matches = [job for job in jobs if job.get("id") == job_id]
        if len(matches) != 1:
            evidence[job_id] = {"available": False, "job_id": job_id,
                                "error": "registered job missing or ambiguous"}
            continue
        job = matches[0]
        schedule = job.get("schedule")
        evidence[job_id] = {
            "available": True, "job_id": job_id,
            **{key: job.get(key) for key in (
                "enabled", "state", "paused_at", "last_run_at", "last_status",
            )},
            "schedule": schedule.get("expr") if isinstance(schedule, dict) else schedule,
        }
    return evidence


def evaluate_source(
    policy: SourcePolicy,
    *,
    now: datetime,
    corpus: Mapping[str, EntryEvidence],
    elasticsearch: Mapping[str, EntryEvidence],
    tasks: Mapping[str, TaskEvidence],
    upstream: Optional[UpstreamEvidence] = None,
    scheduler: Optional[Mapping[str, Any]] = None,
    corpus_es_skew_minutes: int = 10,
) -> SourceHealth:
    result = SourceHealth(
        key=policy.key,
        kind=policy.kind,
        status="healthy",
        schedule=policy.schedule,
        task=policy.task,
        entry_sources=list(policy.entry_sources),
    )
    if policy.monitor_mode in {"manual", "unscheduled"}:
        result.status = "unmonitored"
        result.reasons.append(f"{policy.monitor_mode} source has no freshness SLA")
        return result
    if policy.monitor_mode == "self":
        result.status = "healthy"
        result.reasons.append("current health run is the heartbeat")
        return result

    paused = False
    if policy.monitor_mode == "hermes" and policy.hermes_job_id:
        scheduler = scheduler or {"available": False, "error": "scheduler evidence not found"}
        result.evidence["scheduler"] = dict(scheduler)
        verified = scheduler.get("available") is True and scheduler.get("job_id") == policy.hermes_job_id
        paused = verified and scheduler.get("enabled") is False and scheduler.get("state") == "paused"
        if not verified:
            result.status = "degraded"
            result.reasons.append("Hermes scheduler evidence is unavailable")
        elif paused:
            result.status = "unmonitored"
            result.reasons.append("Hermes job is explicitly paused; freshness SLA suspended")
        elif scheduler.get("enabled") is not True:
            result.status = "degraded"
            result.reasons.append("Hermes job is not enabled and has no verified pause")
        if verified and scheduler.get("last_status") == "error":
            result.status = "failed"
            result.reasons.append("latest observed Hermes execution failed")

    heartbeat = tasks.get(policy.task, TaskEvidence(available=False, error="heartbeat not found"))
    task_age = _age_hours(now, heartbeat.when)
    recent_failure = bool(
        heartbeat.last_failed
        and heartbeat.last_failed.year > 2001
        and (
            heartbeat.when is None
            or abs((heartbeat.when - heartbeat.last_failed).total_seconds()) <= 300
        )
    )
    result.evidence["task"] = {
        "last_run": _iso(heartbeat.when),
        "last_success": _iso(heartbeat.when) if heartbeat.when and not recent_failure else None,
        "last_failed": _iso(heartbeat.last_failed),
        "age_hours": round(task_age, 2) if task_age is not None else None,
        "passed": heartbeat.passed,
        "failed": heartbeat.failed,
        "available": heartbeat.available,
    }
    if policy.related_tasks:
        result.evidence["related_tasks"] = {
            task: {
                "last_run": _iso(tasks.get(task, TaskEvidence()).when),
                "last_failed": _iso(tasks.get(task, TaskEvidence()).last_failed),
                "available": tasks.get(task, TaskEvidence()).available,
            }
            for task in policy.related_tasks
        }
    if not heartbeat.available and not paused:
        result.status = "degraded" if result.status != "failed" else result.status
        result.reasons.append("task heartbeat evidence is unavailable")
    elif recent_failure:
        result.status = "failed"
        result.reasons.append("latest observed task execution failed")
    elif not paused and policy.task_max_age_hours is not None and (
        task_age is None or task_age > policy.task_max_age_hours
    ):
        result.status = "failed"
        result.reasons.append("scheduled task heartbeat is stale or missing")

    if not policy.expects_entry:
        _finish_diagnosis(result, policy)
        return result

    corpus_latest = _latest(corpus.get(source, EntryEvidence()) for source in policy.entry_sources)
    es_latest = _latest(elasticsearch.get(source, EntryEvidence()) for source in policy.entry_sources)
    entry_age = _age_hours(now, corpus_latest.when)
    result.evidence["corpus"] = {
        "last_entry": _iso(corpus_latest.when),
        "entry_id": corpus_latest.entry_id or None,
        "entry_ids": list(corpus_latest.entry_ids),
        "age_hours": round(entry_age, 2) if entry_age is not None else None,
        "available": corpus_latest.available,
    }
    result.evidence["elasticsearch"] = {
        "last_entry": _iso(es_latest.when),
        "entry_id": es_latest.entry_id or None,
        "entry_ids": list(es_latest.entry_ids),
        "available": es_latest.available,
        "error": es_latest.error or None,
    }

    if not corpus_latest.available:
        result.status = "degraded" if result.status != "failed" else result.status
        result.reasons.append("Markdown corpus evidence is unavailable")
    if not es_latest.available:
        result.status = "degraded" if result.status != "failed" else result.status
        result.reasons.append("Elasticsearch evidence is unavailable")
    elif corpus_latest.when and not es_latest.when:
        result.status = "failed"
        result.reasons.append("Markdown entry has no Elasticsearch projection")
    elif es_latest.when and not corpus_latest.when:
        result.status = "failed"
        result.reasons.append("Elasticsearch entry has no Markdown source record")
    elif corpus_latest.when and es_latest.when:
        skew = abs((corpus_latest.when - es_latest.when).total_seconds()) / 60
        corpus_ids = set(corpus_latest.entry_ids or ((corpus_latest.entry_id,) if corpus_latest.entry_id else ()))
        es_ids = set(es_latest.entry_ids or ((es_latest.entry_id,) if es_latest.entry_id else ()))
        ids_disagree = bool(corpus_ids and es_ids and corpus_ids != es_ids)
        timestamps_disagree_without_ids = bool(
            not corpus_latest.entry_id
            and not es_latest.entry_id
            and skew > corpus_es_skew_minutes
        )
        if ids_disagree or timestamps_disagree_without_ids:
            result.status = "failed"
            result.reasons.append("latest Markdown and Elasticsearch entries do not match")

    if upstream:
        result.evidence["upstream"] = {
            "available": upstream.available,
            "latest_activity": _iso(upstream.latest_activity),
            "latest_capture": _iso(upstream.latest_capture),
            "pending": upstream.pending,
            "details": list(upstream.details),
        }
        if policy.upstream_probe and not upstream.available:
            result.status = "degraded" if result.status != "failed" else result.status
            result.reasons.append("upstream capture evidence is unavailable")
        capture_boundary = upstream.latest_capture or corpus_latest.when
        if upstream.latest_activity and (
            capture_boundary is None
            or upstream.latest_activity > capture_boundary + timedelta(hours=1)
        ):
            result.status = "failed"
            result.reasons.append("upstream activity is newer than captured audit evidence")
        if upstream.pending and upstream.pending > 0:
            result.status = "failed"
            result.reasons.append(f"capture spool contains {upstream.pending} pending event(s)")

    if not paused and policy.entry_max_age_hours is not None and (
        entry_age is None or entry_age > policy.entry_max_age_hours
    ):
        upstream_active = bool(
            upstream
            and upstream.latest_activity
            and (not corpus_latest.when or upstream.latest_activity > corpus_latest.when)
        )
        if upstream_active or not policy.allow_empty:
            result.status = "failed"
            result.reasons.append("latest corpus entry is older than the source freshness SLA")
        elif result.status == "healthy":
            result.status = "healthy-empty"
            result.reasons.append("task ran successfully and no upstream activity requires an entry")

    _finish_diagnosis(result, policy)
    return result


def _finish_diagnosis(result: SourceHealth, policy: SourcePolicy) -> None:
    joined = " ".join(result.reasons).lower()
    task_fresh = bool(result.evidence.get("task", {}).get("last_run")) and "heartbeat is stale" not in joined
    if "upstream activity is newer" in joined:
        result.suspected_cause = (
            "The upstream source is active but the capture/audit boundary is stale; "
            "collector wiring or checkpoint delivery likely stopped."
        )
        if task_fresh:
            result.suspected_cause += " The scheduled ingest is still running but has no captured input."
        result.recommendations.extend([
            "Inspect the upstream collector, lifecycle hook, spool path, and checkpoint before retrying ingest.",
            "Backfill the bounded upstream gap, then regenerate dependent rollups.",
        ])
    if "heartbeat" in joined:
        result.suspected_cause = result.suspected_cause or (
            "The expected Celery execution was not observed within its schedule and grace period."
        )
        result.recommendations.append("Inspect Beat uptime, queue routing, worker coverage, expiry, and task logs.")
    if "elasticsearch" in joined or "do not match" in joined:
        result.suspected_cause = result.suspected_cause or (
            "The canonical Markdown record and rebuildable Elasticsearch projection diverged."
        )
        result.recommendations.append(
            "Run scripts/agents/hfl/reconcile_elasticsearch.py read-only, then use --apply if the plan is bounded."
        )
    if "pending event" in joined:
        result.recommendations.append("Retry the existing idempotent ingest task for the retained spool events.")
    if result.status in {"failed", "degraded"} and policy.auto_retry:
        result.recommendations.append(
            "The registry permits an idempotent retry after validating task arguments and a maximum 15-day window."
        )
    result.recommendations = list(dict.fromkeys(result.recommendations))


def probe_agent_sessions(
    *,
    now: datetime,
    pair_loader: Optional[Callable[..., list[dict[str, Any]]]] = None,
) -> UpstreamEvidence:
    tz = ZoneInfo(str(now.tzinfo)) if str(now.tzinfo) else ZoneInfo("Asia/Singapore")
    from scripts.agents.hfl.capture_session_event import audit_root

    root = audit_root() / "events"
    latest_capture: Optional[datetime] = None
    pending = 0
    if root.is_dir():
        for path in root.rglob("*.json"):
            if path.name.startswith("._"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            captured = _parse_when(payload.get("timestamp"), default_tz=tz)
            captured = captured or datetime.fromtimestamp(path.stat().st_mtime, tz=tz)
            if latest_capture is None or captured > latest_capture:
                latest_capture = captured
            ingest = payload.get("ingest") if isinstance(payload.get("ingest"), dict) else {}
            if not ingest.get("entry_id"):
                pending += 1

    state_path = Path(os.environ.get("HERMES_STATE_DB", "~/.hermes/state.db")).expanduser()
    custom_pair_loader = pair_loader is not None
    if pair_loader is None:
        from scripts.agents.hfl.migrate_hermes_sessions import collect_session_pairs

        pair_loader = collect_session_pairs
    since = (
        latest_capture + timedelta(microseconds=1)
        if latest_capture
        else now - timedelta(days=15)
    )
    pairs = (
        pair_loader(state_path, since=since, until=now)
        if state_path.is_file() or custom_pair_loader
        else []
    )
    eligible_times = [
        parsed
        for pair in pairs
        if (parsed := _parse_when(pair.get("timestamp"), default_tz=tz)) is not None
    ]
    latest_activity = max(eligible_times) if eligible_times else None
    details = (f"eligible closed CLI/Telegram pairs after capture: {len(pairs)}",)
    available = root.is_dir() or state_path.is_file()
    return UpstreamEvidence(
        latest_activity=latest_activity,
        latest_capture=latest_capture,
        pending=pending,
        available=available,
        details=details + (f"audit spool: {root}",),
    )


def load_live_corpus_evidence(
    entry_sources: Iterable[str],
) -> dict[str, EntryEvidence]:
    from scripts.agents.hfl.reconcile_elasticsearch import scan_corpus
    from workflows.hfl.tasks.capture import resolve_corpus_dir

    wanted = set(entry_sources)
    output = {source: EntryEvidence() for source in wanted}
    corpus_dir = resolve_corpus_dir()
    try:
        scanned = scan_corpus(corpus_dir)
    except Exception as exc:  # noqa: BLE001 - availability is evidence
        return {
            source: EntryEvidence(available=False, error=type(exc).__name__)
            for source in wanted
        }
    latest_ids: dict[str, set[str]] = {source: set() for source in wanted}
    for doc in scanned.documents.values():
        source = str(doc.get("source") or "")
        if source not in wanted:
            continue
        parsed = _parse_when(doc.get("when"), default_tz=ZoneInfo("Asia/Singapore"))
        entry_id = str(doc.get("entry_id") or "")
        current = output[source]
        if parsed and (not current.when or parsed > current.when):
            latest_ids[source] = {entry_id} if entry_id else set()
            output[source] = EntryEvidence(parsed, entry_id)
        elif parsed and current.when and parsed == current.when and entry_id:
            latest_ids[source].add(entry_id)
    for source, ids in latest_ids.items():
        if ids:
            current = output[source]
            ordered = tuple(sorted(ids))
            output[source] = EntryEvidence(
                current.when, current.entry_id or ordered[0], entry_ids=ordered
            )
    if "summarize" in wanted and corpus_dir.is_dir():
        artifacts = [
            path
            for path in corpus_dir.rglob("*-rollup.md")
            if not any(part.startswith(".") for part in path.relative_to(corpus_dir).parts)
        ]
        if artifacts:
            latest_artifact = max(artifacts, key=lambda path: path.stat().st_mtime)
            output["summarize"] = EntryEvidence(
                datetime.fromtimestamp(
                    latest_artifact.stat().st_mtime,
                    tz=ZoneInfo("Asia/Singapore"),
                )
            )
    return output


def load_live_es_evidence(entry_sources: Iterable[str]) -> dict[str, EntryEvidence]:
    from workflows.hfl.es_store import query_hfl_entries_status

    output: dict[str, EntryEvidence] = {}
    tz = ZoneInfo("Asia/Singapore")
    for source in sorted(set(entry_sources)):
        result = query_hfl_entries_status(source=source, limit=500)
        if not result.available:
            output[source] = EntryEvidence(available=False, error=result.error)
            continue
        rows = [
            row for row in result.rows
            if str(row.get("source") or "").strip() == source
        ]
        if result.rows and not rows:
            output[source] = EntryEvidence(
                available=False, error="exact_source_mismatch"
            )
            continue
        latest_when: Optional[datetime] = None
        latest_ids: set[str] = set()
        for row in rows:
            parsed = _parse_when(row.get("when"), default_tz=tz)
            entry_id = str(row.get("entry_id") or "")
            if parsed and (latest_when is None or parsed > latest_when):
                latest_when = parsed
                latest_ids = {entry_id} if entry_id else set()
            elif parsed and parsed == latest_when and entry_id:
                latest_ids.add(entry_id)
        ordered = tuple(sorted(latest_ids))
        output[source] = EntryEvidence(
            latest_when,
            ordered[0] if ordered else "",
            entry_ids=ordered,
        )
    return output


def load_live_task_evidence(task_paths: Iterable[str]) -> dict[str, TaskEvidence]:
    try:
        from core.apps.es_logging.app.elasticsearch import LOGGING_INDEX, get_index_data
        from core.apps.es_logging.models.document import DtoFunctionLogger

        docs = get_index_data(LOGGING_INDEX, type_hook=DtoFunctionLogger)
    except Exception as exc:  # noqa: BLE001 - availability is evidence
        return {
            task: TaskEvidence(available=False, error=type(exc).__name__)
            for task in task_paths
        }
    tz = ZoneInfo("Asia/Singapore")
    by_name = {str(getattr(doc, "name", "")): doc for doc in docs or []}
    output = {}
    for task in set(task_paths):
        doc = by_name.get(task)
        if doc is None:
            output[task] = TaskEvidence(available=True)
            continue
        output[task] = TaskEvidence(
            when=_parse_when(getattr(doc, "date", None), default_tz=tz),
            last_failed=_parse_when(getattr(doc, "last_failed", None), default_tz=tz),
            passed=float(getattr(doc, "passed", 0) or 0),
            failed=float(getattr(doc, "failed", 0) or 0),
        )
    return output


def scan_activity_corpus_sources(
    *,
    mode: str = "daily",
    policy_path: Path = DEFAULT_POLICY_PATH,
    now: Optional[datetime] = None,
    corpus_loader: Callable[[Iterable[str]], Mapping[str, EntryEvidence]] = load_live_corpus_evidence,
    es_loader: Callable[[Iterable[str]], Mapping[str, EntryEvidence]] = load_live_es_evidence,
    task_loader: Callable[[Iterable[str]], Mapping[str, TaskEvidence]] = load_live_task_evidence,
    upstream_loader: Callable[..., UpstreamEvidence] = probe_agent_sessions,
) -> HealthSnapshot:
    settings, policies = load_source_registry(policy_path)
    tz_name = str(settings.get("timezone") or "Asia/Singapore")
    tz = ZoneInfo(tz_name)
    now = (now or datetime.now(tz)).astimezone(tz)
    monitored = [
        policy
        for policy in policies
        if policy.monitor_mode not in {"manual", "unscheduled", "self"}
    ]
    entry_sources = [source for policy in monitored for source in policy.entry_sources]
    corpus = corpus_loader(entry_sources)
    elasticsearch = es_loader(entry_sources)
    tasks = task_loader(
        task
        for policy in monitored
        for task in (policy.task, *policy.related_tasks)
        if task
    )
    schedulers = load_hermes_scheduler_evidence(
        policy.hermes_job_id for policy in monitored
        if policy.monitor_mode == "hermes" and policy.hermes_job_id
    )
    upstream: dict[str, UpstreamEvidence] = {}
    for policy in policies:
        if policy.upstream_probe == "agent-sessions":
            try:
                upstream[policy.key] = upstream_loader(now=now)
            except Exception as exc:  # noqa: BLE001 - availability is evidence
                upstream[policy.key] = UpstreamEvidence(
                    available=False, details=(f"probe failed: {type(exc).__name__}",)
                )
    results = [
        evaluate_source(
            policy,
            now=now,
            corpus=corpus,
            elasticsearch=elasticsearch,
            tasks=tasks,
            upstream=upstream.get(policy.key),
            scheduler=schedulers.get(policy.hermes_job_id),
            corpus_es_skew_minutes=int(settings.get("corpus_es_skew_minutes", 10)),
        )
        for policy in policies
    ]
    registry_errors = validate_registry_coverage(policies)
    return HealthSnapshot(
        generated_at=now.isoformat(),
        mode=mode,
        timezone=tz_name,
        max_backfill_days=int(settings.get("max_backfill_days", 15)),
        sources=results,
        registry_errors=registry_errors,
        correlation_id=f"hfl-source-health-{now:%Y%m%dT%H%M%S%z}",
    )


def render_failure_report(snapshot: HealthSnapshot) -> str:
    lines = [
        "# HFL Activity Corpus Source Failures",
        "",
        f"Generated: {snapshot.generated_at}",
        f"Correlation ID: {snapshot.correlation_id or 'not assigned'}",
        f"Mode: {snapshot.mode}",
        f"Status: {snapshot.status}",
        f"Failed/degraded sources: {len(snapshot.failures) + len(snapshot.registry_errors)}",
    ]
    for error in snapshot.registry_errors:
        lines.extend(["", "## Registry coverage", "", f"- {error}"])
    for item in snapshot.failures:
        task = item.evidence.get("task", {})
        corpus = item.evidence.get("corpus", {})
        es = item.evidence.get("elasticsearch", {})
        lines.extend([
            "",
            f"## {item.key}",
            "",
            f"- Status: {item.status}",
            f"- Expected schedule: {item.schedule}",
            f"- Task: `{item.task}`",
            f"- Last task heartbeat: {task.get('last_run') or 'not observed'}",
            f"- Last successful execution: {task.get('last_success') or 'not observed'}",
            f"- Last corpus entry: {corpus.get('last_entry') or 'not observed'}",
            f"- Last Elasticsearch document: {es.get('last_entry') or 'not observed'}",
            f"- Suspected cause: {item.suspected_cause or 'requires adaptive investigation'}",
            "- Evidence:",
        ])
        lines.extend(f"  - {reason}" for reason in item.reasons)
        upstream = item.evidence.get("upstream")
        if upstream:
            lines.extend([
                f"  - Upstream latest activity: {upstream.get('latest_activity') or 'not observed'}",
                f"  - Capture/audit latest activity: {upstream.get('latest_capture') or 'not observed'}",
                f"  - Pending captured events: {upstream.get('pending') if upstream.get('pending') is not None else 'unknown'}",
            ])
        lines.append("- Actions performed:")
        if item.actions:
            for action in item.actions:
                lines.append(f"  - {action.get('summary') or action.get('action') or 'recorded action'}")
        else:
            lines.append("  - None during deterministic scan.")
        lines.append("- Recommendations:")
        lines.extend(f"  - {recommendation}" for recommendation in item.recommendations)
        lines.extend([
            f"- Task/commit identifiers: {', '.join(str(action.get('id')) for action in item.actions if action.get('id')) or 'none'}",
            f"- Remaining risk: {'unresolved' if item.status in {'failed', 'degraded'} else 'none'}",
        ])
    return "\n".join(lines).rstrip() + "\n"


def write_failure_report(
    snapshot: HealthSnapshot, *, results_dir: Optional[Path] = None,
) -> Optional[Path]:
    if not snapshot.failures and not snapshot.registry_errors:
        return None
    if results_dir is None:
        settings, _ = load_source_registry()
        results_dir = REPO_ROOT / str(settings.get("results_dir") or "results/hfl")
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(snapshot.generated_at).strftime("%Y%m%d-%H%M%S")
    path = results_dir / f"activity-corpus-source-failures-{snapshot.mode}-{stamp}.md"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(render_failure_report(snapshot), encoding="utf-8")
    os.replace(temporary, path)
    return path


def snapshot_from_dict(payload: Mapping[str, Any]) -> HealthSnapshot:
    return HealthSnapshot(
        generated_at=str(payload["generated_at"]),
        mode=str(payload["mode"]),
        timezone=str(payload["timezone"]),
        max_backfill_days=int(payload.get("max_backfill_days", 15)),
        sources=[SourceHealth(**item) for item in payload.get("sources", [])],
        registry_errors=list(payload.get("registry_errors", [])),
        correlation_id=str(payload.get("correlation_id", "")),
    )
