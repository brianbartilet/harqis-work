"""HFL rendering and persistence for fleet and per-fork scan outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry


def _capability_text(capabilities: dict[str, list[str]]) -> str:
    lines = []
    for category, values in capabilities.items():
        if values:
            lines.append(f"- {category.replace('_', ' ')}: {', '.join(values)}")
    return "\n".join(lines) or "- No HARQIS component-level tree differences detected."


def fork_entry(report: dict[str, Any], *, when: datetime) -> HflEntry:
    repository = str(report.get("repository") or "unknown")
    status = str(report.get("status") or "unknown")
    if status == "ok":
        missing = int(report.get("missing_upstream_commits", 0))
        fork_only = int(report.get("fork_only_commits", 0))
        what = (
            f"Compared `{repository}` with `{report.get('source_ref', 'upstream')}`. "
            f"The fork is missing {missing} upstream commit(s) and has {fork_only} fork-only commit(s).\n\n"
            "HARQIS capability drift:\n" + _capability_text(report.get("capabilities", {}))
        )
        exclusion_counts = {
            key: len(values) for key, values in report.get("intentional_exclusions", {}).items() if values
        }
        if exclusion_counts:
            what += "\n\nIntentional manifest exclusions: " + ", ".join(
                f"{key}={count}" for key, count in sorted(exclusion_counts.items())
            )
        why = (
            f"Tracked {len(report.get('branches', []))} branch(es), "
            f"{len(report.get('pull_requests', []))} pull request(s), and "
            f"{len(report.get('ci_runs', []))} recent CI run(s)."
        )
        readiness = report.get("feature_readiness", {})
        if readiness:
            why += (
                f" General feature readiness: {readiness.get('level', 'unknown')} — "
                + "; ".join(readiness.get("reasons", []))
                + "."
            )
    else:
        what = f"Fork scan failed for `{repository}`: {report.get('error', 'unknown error')}"
        why = "The fork remains in the fleet report so access or configuration drift can be repaired."
    return HflEntry(
        when=when,
        moment=f"Weekly fork drift scan — {repository}",
        what_happened=what,
        why_it_stayed=why,
        possible_use="Choose commits to cherry-pick, open a fork PR, or plan regression and deployment work.",
        tags=("git-forks", "git", re_slug(repository), f"status-{status}"),
        references=tuple(str(value) for value in report.get("references", []) if value),
    )


def fleet_entry(report: dict[str, Any], *, when: datetime) -> HflEntry:
    summary = report.get("summary", {})
    references = []
    for fork in report.get("repositories", []):
        references.extend(fork.get("references", []))
    if report.get("report_path"):
        references.append(str(report["report_path"]))
    return HflEntry(
        when=when,
        moment=f"Weekly fork fleet scan — {summary.get('total', 0)} instance(s)",
        what_happened=(
            f"Scanned {summary.get('healthy', 0)} accessible fork(s); "
            f"{summary.get('errors', 0)} failed. Across the fleet, "
            f"{summary.get('missing_upstream_commits', 0)} upstream commit(s) are missing and "
            f"{summary.get('fork_only_commits', 0)} fork-only commit(s) remain."
        ),
        why_it_stayed="This fleet-level index complements the separate, searchable HFL entry written for every fork instance.",
        possible_use="Review fleet health and choose repositories requiring synchronization, tests, or deployment.",
        tags=("git-forks", "git", "fork-fleet"),
        references=tuple(dict.fromkeys(str(value) for value in references if value)),
    )


def re_slug(repository: str) -> str:
    return "-".join(part for part in repository.lower().replace("/", "-").split("-") if part)


def persist_scan_entries(report: dict[str, Any]) -> dict[str, Any]:
    """Write one entry per fork instance and one fleet summary entry."""
    when = datetime.now().astimezone().replace(tzinfo=None)
    week = when.strftime("%G-W%V")
    outcomes = []
    for fork in report.get("repositories", []):
        repository = str(fork.get("repository") or "unknown")
        entry = fork_entry(fork, when=when)
        outcomes.append(submit_hfl_entry(
            entry, source="git", synthesized=False,
            dedup_key=f"git-forks:{week}:{repository}",
            replace_duplicate=True,
        ))
    summary = submit_hfl_entry(
        fleet_entry(report, when=when), source="git", synthesized=False,
        dedup_key=f"git-forks:{week}:fleet-summary",
        replace_duplicate=True,
    )
    return {"fork_entries": outcomes, "fleet_entry": summary, "entries": len(outcomes) + 1}


def rollout_entry(report: dict[str, Any], result: dict[str, Any], *, when: datetime) -> HflEntry:
    repository = str(result.get("repository") or "unknown")
    status = str(result.get("status") or "unknown")
    references = []
    pull_request = result.get("pull_request") or {}
    if pull_request.get("url"):
        references.append(str(pull_request["url"]))
    if report.get("report_path"):
        references.append(str(report["report_path"]))
    return HflEntry(
        when=when,
        moment=f"Fork feature rollout — {repository}",
        what_happened=(
            f"Plan `{report.get('plan_id', 'unknown')}` finished for `{repository}` with "
            f"status `{status}`. Targeted tests: "
            f"{(result.get('targeted_tests') or {}).get('success', 'not-run')}; full tests: "
            f"{(result.get('full_tests') or {}).get('success', 'not-run')}; deployment: "
            f"{(result.get('deployment') or {}).get('success', 'not-requested')}."
        ),
        why_it_stayed="Preserves the reviewed plan, validation gates, and publication outcome for this fork.",
        possible_use="Audit a rollout, investigate a failed fork, or compare feature adoption across derivatives.",
        tags=("git-forks", "git", "fork-feature-rollout", re_slug(repository), f"status-{status}"),
        references=tuple(references),
    )


def rollout_fleet_entry(report: dict[str, Any], *, when: datetime) -> HflEntry:
    summary = report.get("summary", {})
    references = [str(report["report_path"])] if report.get("report_path") else []
    references.extend(
        str((result.get("pull_request") or {}).get("url"))
        for result in report.get("results", [])
        if (result.get("pull_request") or {}).get("url")
    )
    return HflEntry(
        when=when,
        moment=f"Fork fleet feature rollout — plan {report.get('plan_id', 'unknown')}",
        what_happened=(
            f"Processed {summary.get('total', 0)} fork(s): {summary.get('draft_prs', 0)} draft PR(s), "
            f"{summary.get('direct_main', 0)} direct default-branch delivery(s), "
            f"{summary.get('failed', 0)} failure(s), and {summary.get('skipped', 0)} skipped target(s)."
        ),
        why_it_stayed="This fleet summary indexes the separate per-fork rollout audit entries.",
        possible_use="Review fleet adoption and decide which blocked or failed forks need manual follow-up.",
        tags=("git-forks", "git", "fork-feature-rollout", "fork-fleet"),
        references=tuple(dict.fromkeys(references)),
    )


def persist_rollout_entries(report: dict[str, Any]) -> dict[str, Any]:
    """Write one HFL audit event per rollout target plus one fleet summary."""
    when = datetime.now().astimezone().replace(tzinfo=None)
    run_key = str(report.get("generated_at") or when.isoformat())
    plan_id = str(report.get("plan_id") or "unknown")
    outcomes = []
    for result in report.get("results", []):
        repository = str(result.get("repository") or "unknown")
        outcomes.append(submit_hfl_entry(
            rollout_entry(report, result, when=when), source="git", synthesized=False,
            dedup_key=f"git-forks-rollout:{plan_id}:{repository}:{run_key}",
        ))
    summary = submit_hfl_entry(
        rollout_fleet_entry(report, when=when), source="git", synthesized=False,
        dedup_key=f"git-forks-rollout:{plan_id}:fleet:{run_key}",
    )
    return {"fork_entries": outcomes, "fleet_entry": summary, "entries": len(outcomes) + 1}
