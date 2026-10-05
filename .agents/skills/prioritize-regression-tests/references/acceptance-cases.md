# Behavioral acceptance cases

These are synthetic review fixtures, not observations about ICON or live Xray.
Use them to review changes to the playbook and to exercise an agent with supplied
fixture data. Do not claim they are automated integration tests.

| Case | Supplied evidence | Required result |
|---|---|---|
| Direct change coverage | Story DEMO-1 criterion explicitly linked to active DEMO-101 with matching manual assertions; no criticality evidence | Story > DEMO-101 > exact step locator, high confidence, P1. Preserve steps and expected results. |
| Shared test | Story DEMO-1 and Bug DEMO-2 both map to the same executable scenario in DEMO-101 | Two traceability rows but one execution unit; retain both change keys and highest applicable tier. |
| Unlinked behavioral match | DEMO-102 assertions directly exercise DEMO-2's changed behavior, no Jira link | Medium confidence, inferred mapping with both source locators, P1; not ignored just because it lacks a link. |
| Weak critical candidate | Security-critical change and DEMO-103 share labels but scenario assertions are unreadable | Low-confidence P0 candidate in review, not confirmed covered or silently demoted. |
| Missing coverage | No repository scenario covers one criterion of DEMO-1 | Criterion-level gap despite another mapped criterion; no fabricated Test ID or Gherkin counted as existing coverage. |
| Stale scenario | DEMO-104 expects an outcome explicitly removed by the change | Maintain risk tier but mark needs maintenance, not runnable unchanged; expose contradictory assertion. |
| Eligibility | One approved active Test is Done; another is obsolete; a third has an undocumented lifecycle status | Include Done under verified policy, exclude obsolete with reason, hold unknown for eligibility review. Last-run failure does not exclude a Test. |
| Pagination/folders | Parent folder has two pages and one child; one Test appears in both | Read every page/child, retain associations, count unique Test once. Failed child read makes analysis partial. |
| Broken paging | Advertised total exceeds retrieved records; next page is empty or repeats a cursor | Stop boundedly with a completeness error, not an infinite loop or complete-empty claim. |
| Board scope | Board has two active sprints, including resolved Stories | Ask which sprint(s); after selection include Done changes. Never substitute all project open issues. |
| Release scope | Same version name exists in two projects; an issue has only affectedVersion | Resolve project-specific fixVersion IDs; do not include affectedVersion-only issue. |
| Combined selectors | Board and fixVersion provided with no combination rule | Ask union/intersection, then record the selected rule; no accidental scope widening. |
| Outline/manual counts | Stored outline has three Examples rows; manual test has four sequential steps | Report one outline definition with three instances and one manual case; no four independent manual tests invented. |
| Generic test | Only an automation path is visible, assertions unavailable | Preserve reference, state scenario unavailable, do not count scenario-level coverage. |
| Dependency | P0 requires a P2 setup test, or two tests depend on each other | Setup executes first with explanation; cycles are blocked and visible. |
| Budget | P0/P1 known durations exceed budget and one P1 has unknown duration | Report insufficient budget and unknown estimate; do not silently omit mandatory work or treat unknown as zero. |
| No budget | One relevant active test and one unrelated active baseline test | Prioritized subset plus full eligible baseline, latter P3 unless an evidenced smoke/core rule promotes it. |
| Missing access | Xray read returns 403 or browser sign-in while Jira summaries work | Exact unavailable capability/resource and partial/blocked report; no claim repository bodies were read. |
| Export fallback | Owner supplies complete dated test/scenario export but live Xray is unavailable | Analyze export scope, disclose freshness/visibility limits, do not pretend it is a live snapshot. |
| Output safety | Step contains commas/newlines or spreadsheet formula-leading text | Valid escaped CSV, safe display cells, preserved meaning and no secrets; Markdown links resolve. |
| Read-only suite | Owner asks only for a regression suite | Local report/CSV only; no Jira creation, test execution, credential changes or scheduler edits. |

## Review procedure

1. For each row, trace the applicable rule in SKILL.md or integration-notes.md.
2. Record pass/fail for instruction coverage; revise missing or conflicting rules.
3. For a live run, separately validate actual acquisition and output artifacts.
4. Report instruction review separately from live service validation. Passing this
   checklist does not establish credentials, Xray compatibility or executed tests.
