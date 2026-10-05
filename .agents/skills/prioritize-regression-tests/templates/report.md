# Regression prioritization report

> Template: replace placeholders with observed evidence. Do not present this empty
> template as a completed run. No tests have been executed by this analysis.

## Summary and decision

- Analysis status: complete / partial / blocked, with reason.
- Snapshot time/timezone; target release/sprint, build/environment if provided.
- Highest-risk runnable checks and high-risk blocked/review items.
- Important uncovered criteria and next decision for the owner.
- Limitation: coverage is bounded by the existing repository and accessible evidence;
  a mapping is not a passing execution or proof of exhaustive product coverage.

## Scope and acquisition

| Item | Resolved value and source |
|---|---|
| Repository project/folder or explicit test list | |
| Descendant folders included | |
| Board and sprint IDs / projects and fixVersion IDs / explicit issue list | |
| Union/intersection when selectors combine | |
| Active-test policy and exclusions | |
| Jira/Xray edition, integration and capability checks | |
| Final selectors/JQL and source timestamps | |
| Pages, source totals, unique records and reconciliation | |
| Inaccessible objects, unknown visibility, truncation or stale exports | |
| Budget, ordering overrides and assumptions | |

## Inventory and coverage totals

Report distinct Stories/Bugs, active Tests, ambiguous/excluded/unavailable Tests,
scenario definitions, executable units and outline parameter instances separately.
Reconcile eligible Tests across mutually exclusive dispositions: selected now,
deferred baseline, needs review, unrelated. Blocked readiness is a separate property
and may apply to any disposition; never double-count it as another Test.

For each change show supported mapped criteria / total known in-scope criteria;
report partial or unknown denominators rather than inventing a percentage. Use
"candidate" for low-confidence mappings. If useful, separately count changes with
at least one supported mapping; do not label that count full change coverage.

## Story or Bug > Related Tests > scenarios

| Change and criterion/repro | Repository Test | Individual scenario/Gherkin locator and assertion | Relation | Confidence | Evidence and rationale | Gap/staleness |
|---|---|---|---|---|---|---|

Include an explicit row for every unmapped or inaccessible change. Below the table,
include source-preserving scenario/step excerpts sufficient for execution, including
preconditions, action/data/expected results or Gherkin Background/Examples. Link
larger verified scenario files relatively. Do not invent missing bodies.

## Prioritized regression suite

State the ranking and deduplication policy and any overrides. One row per executable
unit, retaining every related change key. Group tags are descriptive, not extra runs.

| Order | Tier | Test / executable scenario | Related changes | Categories | Confidence | Readiness | Why now / evidence | Duration if known |
|---|---|---|---|---|---|---|---|---|---|

[Execution handoff CSV](regression-suite.csv)

## Dependencies and execution waves

List prerequisites, setup/data/environment, blocked units and ownership if known.
Explain dependencies that precede a higher-tier unit and any cycles. Separate
runnable order from blocked/review work; retain original risk tiers in all views.

## Deferred, excluded and review-required work

| Test/issue | Disposition | Risk tier if eligible | Reason/evidence | Residual risk or required decision |
|---|---|---|---|---|

Include budget overflow, unknown durations, ambiguous lifecycle, inactive tests,
out-of-scope links and stale assertions. With no budget, include the full eligible
baseline, not just a shortlist. Do not lose low-confidence high-impact candidates.

## Coverage gaps and optional new scenarios

List missing or contradictory assertions per criterion; distinguish unmapped from
unreadable. Proposed new scenarios, only if requested, are explicitly NOT repository
tests and NOT included in existing-coverage totals or the execution CSV.

## Verification and sources

- Scope, pagination, folder traversal and eligibility reconciled (or limitations).
- Every input and mapping accounted for; counts calculated from saved records.
- CSV and Markdown agree; duplicate units and broken local links checked.
- Jira/Xray read-only; no tests executed or remote entities created unless separately
  authorized and verified with their identifiers.
- Source issue/repository links and scenario locators; no credentials or raw dumps.
