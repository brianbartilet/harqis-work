---
name: manifesto-audit
description: Audit HARQIS workflows, integrations, and agent flows against the current manifesto and architecture, producing evidence-backed findings and prioritized remediation. Use for manifesto audits, CODE/PARA flow reviews, and gaps in operational review or expression.
---

# Manifesto audit

Execute this procedure with the current agent's tools and configured model. No
particular provider, CLI, subscription, or agent profile is required. A scheduler
or caller selects the runtime; do not launch another LLM to perform this skill.

## Scope and inputs

Resolve the checkout with `git rev-parse --show-toplevel`. Accept an optional
scope, output directory, and explicit remediation instructions from the caller.
Default to a repository-wide audit and reports only. Existing authorization for
fixes or draft PRs remains valid; the skill itself does not authorize publishing,
merging, deployment, notifications, or changes to schedules and credentials.

Read `docs/MANIFESTO.md`, applicable repository instructions, and the architecture
documents relevant to the selected flows. Treat the current manifesto as the
project's design authority. Distinguish a demonstrated violation from a proposed
improvement; do not turn a principle into an invented universal requirement.

## Gather evidence

1. Record the branch, commit, working-tree state, scope, and audit time. Preserve
   existing edits. Do not change the branch of a running host checkout.
2. Use the repository virtual environment and the host's standard environment
   bootstrap before importing `apps` or `workflows`. Load configuration without
   displaying credentials. Run
   `scripts/agents/repo-quality/manifesto_audit.py` for metadata findings; its
   nonzero result may indicate violations, not a failed audit. Report execution
   failures separately from findings.
3. Inspect `workflows/*/tasks_config.py`, `apps/`, `agents/`, and recent Git
   history. Use actual commit dates rather than assuming a fixed number of
   commits represents a particular time span. Search with `rg` where available.
4. Optionally inspect `scripts/agents/repo-quality/daily_improvement_scout.py`
   for additional signals. Check its operations and output paths before running
   it; it is supplementary, not a prerequisite or proof of compliance.
5. Trace three to five representative workflows, or all flows in a smaller
   requested scope, from Capture through Organize, Distill, and Express. Cite
   producer, durable storage, transformation, consumer, and observable receipt.

Review:

- Metadata: `code_role`, `para_bucket`, `express_target`, `review_artifact`, and
  `hfl_signal`; distinguish active schedules from disabled scaffolding.
- PAER within each CODE stage: what is planned, analyzed, executed, and reviewed.
- App/service reuse, workflow orchestration boundaries, duplicated logic, and
  ownership of schedules. Preserve the single Celery Beat scheduler invariant.
- HFL capture, recall, distillation, expression, retry behavior, and receipts.
- Test evidence, dead-code candidates, operational failure paths, and drift
  between implementation, documentation, and deployment configuration.

Static code establishes intended behavior, not runtime health. Mark unavailable
runtime evidence as unknown. Never equate missing metadata with a broken flow,
or missing evidence with proof that work was not performed. Do not read private
corpus contents or credentials merely to audit architecture.

## Findings and deliverables

Rank findings by severity and expected impact:

- Critical: demonstrated loss of a core capture/expression path or comparable
  operational failure.
- High: substantiated regression risk or a significant architecture/review gap.
- Medium: bounded maintenance, reuse, or documentation improvements.

Each finding includes an ID, severity, signal, repository-relative evidence with
line numbers, relevant manifesto principle, impact, intended Express output,
smallest next action, and an effort estimate with its uncertainty. Separate
observations, inferences, and recommendations. Avoid arbitrary finding quotas.

Write matching `manifesto_audit_YYYY-MM-DD.md` and
`manifesto_audit_YYYY-MM-DD.json` to the caller's output directory, or
`results/manifesto-audit/` in the checkout. Preserve previous reports using a
timestamp suffix unless the caller supplied exact filenames for a run.

The JSON object contains `audited_at`, `repository_commit`, `scope`,
`runtime` (agent/model when known), `checks`, `findings`, and `limitations`.
Use the finding fields above consistently. Record failed or unavailable checks;
never fabricate model identity, execution results, counts, or PR links.

If remediation is authorized, isolate changes in a worktree, validate each fix,
and follow the repository's commit/PR conventions. Keep findings even when a fix
cannot be completed. Report PR links only after creation succeeds.

Validate that both reports exist and the JSON parses. Finish with severity
counts, the most useful next actions, report paths, validation limitations, and
any authorized remediation results.
